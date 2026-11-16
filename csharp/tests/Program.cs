using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using ByondWire;

static class Tests
{
    static readonly string Root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../.."));
    static readonly string Cli = Path.Combine(Root, "cli/bin", new DirectoryInfo(AppContext.BaseDirectory).Parent!.Name, "net10.0/ByondWire.Cli.dll");
    static int assertions;

    static void Check(bool condition, string message)
    {
        assertions++;
        if (!condition) throw new Exception(message);
    }

    static async Task Throws<T>(Func<Task> action) where T : Exception
    {
        try { await action(); }
        catch (T) { assertions++; return; }
        throw new Exception($"Expected {typeof(T).Name}");
    }

    static byte[] Frame(byte[] body) => [0, 131, (byte)(body.Length >> 8), (byte)body.Length, .. body];
    static byte[] Text(byte[] data) => Frame([6, .. data, 0]);

    sealed class Server : IAsyncDisposable
    {
        readonly TcpListener listener = new(IPAddress.Loopback, 0);
        readonly CancellationTokenSource stop = new(TimeSpan.FromSeconds(12));
        public readonly Task<byte[]> Completion;
        public int Port => ((IPEndPoint)listener.LocalEndpoint).Port;
        public bool Closed;

        public Server(byte[] reply, int delay = 0, bool eof = false)
        {
            listener.Start();
            Completion = Serve(reply, delay, eof);
        }

        async Task<byte[]> Serve(byte[] reply, int delay, bool eof)
        {
            using var peer = await listener.AcceptTcpClientAsync(stop.Token);
            var stream = peer.GetStream();
            var header = new byte[4];
            await stream.ReadExactlyAsync(header, stop.Token);
            var body = new byte[(header[2] << 8) | header[3]];
            await stream.ReadExactlyAsync(body, stop.Token);
            if (delay == 0) await stream.WriteAsync(reply, stop.Token);
            else foreach (byte b in reply)
            {
                await Task.Delay(delay, stop.Token);
                await stream.WriteAsync(new byte[] { b }, stop.Token);
            }
            if (eof) peer.Client.Shutdown(SocketShutdown.Send);
            Closed = await stream.ReadAsync(new byte[1], stop.Token) == 0;
            return [.. header, .. body];
        }

        public async ValueTask DisposeAsync()
        {
            stop.Cancel();
            listener.Stop();
            try { await Completion; }
            catch (Exception e) when (e is OperationCanceledException or IOException or SocketException) { }
            stop.Dispose();
        }
    }

    static async Task<object?> Exchange(byte[] reply, bool raw = false, string query = "status", int delay = 0)
    {
        await using var server = new Server(reply, delay);
        object? result = raw
            ? await Client.TopicRawAsync("127.0.0.1", server.Port, query)
            : await Client.TopicAsync("127.0.0.1", server.Port, query);
        var request = await server.Completion.WaitAsync(TimeSpan.FromSeconds(2));
        var queryBytes = Encoding.UTF8.GetBytes(query.StartsWith('?') ? query : "?" + query);
        Check(request.SequenceEqual(Frame([0, 0, 0, 0, 0, .. queryBytes, 0])), "Request bytes differ");
        Check(server.Closed, "Client failed to close after framed response");
        return result;
    }

    static Task Vectors()
    {
        int count = 0;
        foreach (var line in File.ReadLines(Path.Combine(AppContext.BaseDirectory, "text-vectors.tsv")))
        {
            if (line.StartsWith('#')) continue;
            var fields = line.Split('\t');
            var bytes = Convert.FromHexString(fields[1]);
            if (fields[2] == "-")
            {
                try { Client.DecodeText(bytes); }
                catch (Exception e) when (e is DecoderFallbackException or InvalidDataException) { count++; continue; }
                throw new Exception($"Accepted invalid text vector {fields[0]}");
            }
            Check(Client.DecodeText(bytes) == Encoding.UTF8.GetString(Convert.FromHexString(fields[2])), fields[0]);
            count++;
        }
        Check(count > 0, "No shared text vectors loaded");
        Console.WriteLine($"  {count} shared text vectors");
        Check(Client.DecodeText(Encoding.UTF8.GetBytes(new string('x', 65533))) == new string('x', 65533), "Large decode");
        return Task.CompletedTask;
    }

    static async Task Values()
    {
        Check(await Exchange(Text(Convert.FromHexString("ff16636166c3a9"))) is string s && s == "café", "Native decoded string");
        Check(await Exchange(Text([])) is string empty && empty == "", "Empty text");
        Check(await Exchange(Frame([0])) is null, "Successful null");
        foreach (var (hex, expected) in new[] { ("2a000020c0", -2.5f), ("2a0000803f", 1f), ("2a00000000", 0f) })
            Check(await Exchange(Frame(Convert.FromHexString(hex))) is float f && f == expected, "Native float32");
        byte[] raw = [255, 0, 10, 92, 255, 21, 195, 169, 10];
        Check(await Exchange(Text(raw), raw: true) is byte[] b && b.SequenceEqual(raw), "Raw preservation");
        Check(await Exchange(Text([]), raw: true) is byte[] { Length: 0 }, "Raw empty");
        Check(await Exchange(Frame([0]), raw: true) is null, "Raw null");
        Check(await Exchange(Frame(Convert.FromHexString("2a000020c0")), raw: true) is float n && n == -2.5f, "Raw float");
        byte[] large = Encoding.UTF8.GetBytes(new string('x', 65533));
        Check(await Exchange(Text(large)) is string text && text.Length == 65533, "Maximum response");
        Check(await Exchange(Text("hello"u8.ToArray()), delay: 4) is string fragmented && fragmented == "hello", "Fragmented response");
        foreach (var query in new[] { "?status", "??status", "", "café", "status'; $(id)`id`\\n", new string('x', 280), new string('x', 65528), "?" + new string('x', 65528) })
            Check(await Exchange(Frame([0]), query: query) is null, "Query boundary");
        await using (var maximumTimeout = new Server(Frame([0])))
            Check(await Client.TopicRawAsync("127.0.0.1", maximumTimeout.Port, "status", TimeSpan.FromMilliseconds(int.MaxValue)) is null, "Maximum timeout rejected");
        await using var canonical = new Server(Frame([0]));
        await Client.TopicAsync("127.0.0.1", canonical.Port, "status");
        Check((await canonical.Completion).SequenceEqual(Convert.FromHexString("0083000d00000000003f73746174757300")), "Canonical wire request");
    }

    static async Task Malformed()
    {
        foreach (byte[] reply in new byte[][] { [], [0, 131, 0], [255, 255, 0, 1, 0], Frame([]), Frame([6]), Frame([6, 97]), Frame([7]), Frame([0, 0]), Frame([42, 0]), [0, 131, 0, 10, 6, 97] })
        {
            await using var server = new Server(reply, eof: true);
            try
            {
                await Client.TopicRawAsync("127.0.0.1", server.Port, "status");
                throw new Exception("Accepted malformed response");
            }
            catch (Exception e) when (e is IOException or InvalidDataException) { assertions++; }
            await server.Completion.WaitAsync(TimeSpan.FromSeconds(2));
            Check(server.Closed, "Malformed reply socket leaked");
        }
        foreach (var data in new byte[][] { [255], [255, 27], [195, 255, 21, 169] })
        {
            await using var server = new Server(Text(data));
            try
            {
                await Client.TopicAsync("127.0.0.1", server.Port, "status");
                throw new Exception("Accepted invalid text");
            }
            catch (Exception e) when (e is DecoderFallbackException or InvalidDataException) { assertions++; }
            await server.Completion.WaitAsync(TimeSpan.FromSeconds(2));
            Check(server.Closed, "Decode failure socket leaked");
        }
    }

    static async Task Validation()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        foreach (var query in new[] { "a\0b", new string('x', 65529), new string('é', 32765), "\ud800", null! })
            await Throws<ArgumentException>(async () => await Client.TopicRawAsync("127.0.0.1", port, query));
        foreach (var host in new[] { "", " ", null! })
            await Throws<ArgumentException>(async () => await Client.TopicAsync(host, port, "status"));
        foreach (int invalidPort in new[] { 0, -1, 65536 })
            await Throws<ArgumentException>(async () => await Client.TopicRawAsync("127.0.0.1", invalidPort, "status"));
        foreach (var timeout in new[] { TimeSpan.Zero, TimeSpan.FromTicks(1), TimeSpan.FromMilliseconds(-1), TimeSpan.MaxValue, TimeSpan.FromMilliseconds((double)int.MaxValue + 1) })
            await Throws<ArgumentException>(async () => await Client.TopicRawAsync("127.0.0.1", port, "status", timeout));
        Check(!listener.Pending(), "Invalid input opened a socket");
        listener.Stop();
        await Throws<SocketException>(async () => await Client.TopicAsync("127.0.0.1", port, "status"));
    }

    static async Task Deadlines()
    {
        await using (var idle = new Server([]))
        {
            var watch = Stopwatch.StartNew();
            await Throws<TimeoutException>(async () => await Client.TopicAsync("127.0.0.1", idle.Port, "status", TimeSpan.FromMilliseconds(120)));
            Check(watch.Elapsed < TimeSpan.FromSeconds(2), "Timeout exceeded budget");
            await idle.Completion.WaitAsync(TimeSpan.FromSeconds(2));
            Check(idle.Closed, "Timeout socket leaked");
        }
        await using var drip = new Server(Text("slow"u8.ToArray()), delay: 45);
        var timer = Stopwatch.StartNew();
        await Throws<TimeoutException>(async () => await Client.TopicAsync("127.0.0.1", drip.Port, "status", TimeSpan.FromMilliseconds(140)));
        Check(timer.Elapsed < TimeSpan.FromMilliseconds(450), "Deadline restarted on reads");
    }

    static async Task Hostnames()
    {
        await using var server = new Server(Text("ok"u8.ToArray()));
        var addresses = await Dns.GetHostAddressesAsync("localhost");
        Check(await Client.TopicAsync("localhost", server.Port, "status") is string s && s == "ok", "Hostname/IPv4 fallback");
        await server.Completion;
        Console.WriteLine("  localhost addresses: " + string.Join(", ", addresses.Select(a => a.ToString())));
        if (Socket.OSSupportsIPv6)
        {
            using var listener = new TcpListener(IPAddress.IPv6Loopback, 0);
            listener.Start();
            var task = Client.TopicAsync("::1", ((IPEndPoint)listener.LocalEndpoint).Port, "status");
            using var peer = await listener.AcceptTcpClientAsync();
            var stream = peer.GetStream();
            var request = new byte[17];
            await stream.ReadExactlyAsync(request);
            await stream.WriteAsync(Frame([0]));
            Check(await task is null, "IPv6 numeric host");
        }
    }

    static async Task Fallback()
    {
        await using var server = new Server(Frame([0]));
        using (var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(2)))
        using (var client = await Client.ConnectAsync([IPAddress.Parse("127.0.0.2"), IPAddress.Loopback], server.Port, deadline.Token))
        {
            using var stream = client.GetStream();
            await stream.WriteAsync(Convert.FromHexString("0083000d00000000003f73746174757300"));
            var response = new byte[5];
            await stream.ReadExactlyAsync(response);
            Check(response.SequenceEqual(Convert.FromHexString("0083000100")), "Fallback response");
        }
        await server.Completion;
        Check(server.Closed, "Fallback connection cleanup");
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var candidates = Enumerable.Repeat(IPAddress.Parse("127.0.0.2"), 100000).Append(IPAddress.Loopback).ToArray();
        using var stop = new CancellationTokenSource(TimeSpan.FromMilliseconds(80));
        var watch = Stopwatch.StartNew();
        await Throws<OperationCanceledException>(async () =>
        {
            using var client = await Client.ConnectAsync(candidates, port, stop.Token);
        });
        Check(watch.Elapsed < TimeSpan.FromSeconds(2), "Connection attempts restarted deadline");
        Check(!listener.Pending(), "Opened connection after deadline expired");
    }

    static async Task<(int Code, byte[] Out, string Error)> Invoke(params string[] args)
    {
        using var process = new Process { StartInfo = new ProcessStartInfo(Environment.ProcessPath!) { RedirectStandardOutput = true, RedirectStandardError = true } };
        process.StartInfo.FileName = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH") ?? "dotnet";
        process.StartInfo.Environment["LANG"] = "fr_FR.UTF-8";
        process.StartInfo.ArgumentList.Add(Cli);
        foreach (var arg in args) process.StartInfo.ArgumentList.Add(arg);
        process.Start();
        using var output = new MemoryStream();
        var read = process.StandardOutput.BaseStream.CopyToAsync(output);
        var error = process.StandardError.ReadToEndAsync();
        try { await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(9)); }
        finally { if (!process.HasExited) { process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); } }
        await read;
        return (process.ExitCode, output.ToArray(), await error);
    }

    static async Task CliTests()
    {
        foreach (var (reply, output, code) in new[] {
            (Text([255, 0, 10, 255, 21]), new byte[] { 255, 0, 10, 255, 21 }, 0),
            (Text([]), Array.Empty<byte>(), 0), (Frame([0]), Array.Empty<byte>(), 2),
            (Frame(Convert.FromHexString("2a000020c0")), "-2.5"u8.ToArray(), 0),
            (Frame(Convert.FromHexString("2a0000803f")), "1"u8.ToArray(), 0) })
        {
            await using var server = new Server(reply);
            var result = await Invoke("127.0.0.1", server.Port.ToString(CultureInfo.InvariantCulture), "status");
            Check(result.Code == code && result.Out.SequenceEqual(output) && result.Error == "", "CLI value/exit contract");
            await server.Completion;
        }
        foreach (var args in new[] { Array.Empty<string>(), new[] { "host" }, new[] { "", "4999", "status" }, new[] { "127.0.0.1", "0", "status" }, new[] { "127.0.0.1", "no", "status" }, new[] { "127.0.0.1", "65536", "status" }, new[] { "127.0.0.1", "1", new string('x', 65529) } })
        {
            var result = await Invoke(args);
            Check(result.Code == 1 && result.Out.Length == 0 && result.Error.Length > 0 && !result.Error.Contains(" at "), "CLI argument error");
        }
        using (var refused = new TcpListener(IPAddress.Loopback, 0))
        {
            refused.Start();
            int port = ((IPEndPoint)refused.LocalEndpoint).Port;
            refused.Stop();
            var result = await Invoke("127.0.0.1", port.ToString(), "status");
            Check(result.Code == 1 && result.Out.Length == 0 && result.Error.Length > 0, "CLI connection refusal");
        }
        await using (var bad = new Server(Frame([7])))
        {
            var result = await Invoke("127.0.0.1", bad.Port.ToString(), "status");
            Check(result.Code == 1 && result.Out.Length == 0 && result.Error.Length > 0, "CLI malformed response");
            await bad.Completion;
        }
        await using var idle = new Server([]);
        var timeoutResult = await Invoke("127.0.0.1", idle.Port.ToString(), "status");
        Check(timeoutResult.Code == 124 && timeoutResult.Out.Length == 0 && timeoutResult.Error.Contains("timed out"), "CLI timeout");
        await idle.Completion;
        Check(idle.Closed, "CLI timeout socket leaked");
    }

    static Task SilentLoad()
    {
        var stdout = Console.Out;
        var stderr = Console.Error;
        using var captured = new StringWriter();
        try
        {
            Console.SetOut(captured); Console.SetError(captured);
            var type = typeof(Client);
            System.Runtime.CompilerServices.RuntimeHelpers.RunClassConstructor(type.TypeHandle);
            Check(Client.DecodeText([]) == "", "Empty decode");
        }
        finally { Console.SetOut(stdout); Console.SetError(stderr); }
        Check(captured.ToString() == "", "Library printed during initialization/call");
        return Task.CompletedTask;
    }

    static async Task<int> Main(string[] args)
    {
        if (args.Contains("--benchmark")) { await Benchmark(); return 0; }
        int failures = 0;
        foreach (var (name, test) in new (string, Func<Task>)[] { ("shared text vectors", Vectors), ("native/raw values and framing", Values), ("malformed replies and cleanup", Malformed), ("pre-connect validation", Validation), ("shared deadlines and cleanup", Deadlines), ("hostname and IPv6", Hostnames), ("address fallback and shared connect deadline", Fallback), ("silent library initialization", SilentLoad), ("CLI contract", CliTests) })
        {
            try { await test(); Console.WriteLine($"PASS {name}"); }
            catch (Exception error) { failures++; Console.Error.WriteLine($"FAIL {name}: {error}"); }
        }
        Console.WriteLine($"{assertions} assertions; {failures} failed groups");
        return failures == 0 ? 0 : 1;
    }

    static async Task Benchmark()
    {
        foreach (int size in new[] { 281, 65533 })
        {
            byte[] data = Encoding.UTF8.GetBytes(new string('x', size));
            byte[] reply = Text(data);
            int iterations = size == 281 ? 2000 : 400;
            using var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            int port = ((IPEndPoint)listener.LocalEndpoint).Port;
            int total = 100 + 5 * iterations;
            using var stop = new CancellationTokenSource(TimeSpan.FromMinutes(2));
            var serve = Task.Run(async () =>
            {
                var request = new byte[17];
                for (int i = 0; i < total; i++)
                {
                    using var peer = await listener.AcceptTcpClientAsync(stop.Token);
                    var stream = peer.GetStream();
                    await stream.ReadExactlyAsync(request, stop.Token);
                    await stream.WriteAsync(reply, stop.Token);
                }
            });
            for (int i = 0; i < 100; i++) await Client.TopicAsync("127.0.0.1", port, "status");
            var timings = new List<double>();
            var allocations = new List<long>();
            for (int round = 0; round < 5; round++)
            {
                GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
                long before = GC.GetTotalAllocatedBytes(precise: true);
                var timer = Stopwatch.StartNew();
                for (int i = 0; i < iterations; i++)
                {
                    object? value = await Client.TopicAsync("127.0.0.1", port, "status");
                    if (value is not string text || text.Length != size) throw new Exception("Benchmark payload mismatch");
                }
                timer.Stop();
                timings.Add(timer.Elapsed.TotalMicroseconds / iterations);
                allocations.Add((GC.GetTotalAllocatedBytes(precise: true) - before) / iterations);
            }
            await serve;
            timings.Sort(); allocations.Sort();
            Console.WriteLine($"topic text={size}: median {timings[2]:F2} us/request, {allocations[2]} allocated bytes/request (client+server)");
        }
    }
}
