using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace ByondWire;

/// <summary>Standard-library BYOND Topic client. Each call owns one connection.</summary>
public static class Client
{
    static readonly UTF8Encoding Utf8 = new(false, true);

    /// <summary>Strictly decode UTF-8 runs, removing only supported BYOND markers.</summary>
    public static string DecodeText(ReadOnlySpan<byte> data)
    {
        int marker = data.IndexOf((byte)255);
        if (marker < 0) return Utf8.GetString(data);
        var text = new StringBuilder();
        while (marker >= 0)
        {
            text.Append(Utf8.GetString(data[..marker]));
            if (marker + 1 == data.Length || data[marker + 1] is not
                (6 or 7 or 8 or 9 or 18 or 21 or 22 or 23 or 24 or 25 or >= 31 and <= 38))
                throw new InvalidDataException("Unknown or truncated BYOND text marker");
            data = data[(marker + 2)..];
            marker = data.IndexOf((byte)255);
        }
        return text.Append(Utf8.GetString(data)).ToString();
    }

    /// <summary>Return a string, float, or successful null; errors throw exceptions.</summary>
    public static Task<object?> TopicAsync(string host, int port, string query, TimeSpan? timeout = null) =>
        ExchangeAsync(host, port, query, timeout, raw: false);

    /// <summary>Return original text bytes, float, or null. The default deadline is five seconds.</summary>
    public static Task<object?> TopicRawAsync(string host, int port, string query, TimeSpan? timeout = null) =>
        ExchangeAsync(host, port, query, timeout, raw: true);

    static async Task<object?> ExchangeAsync(string host, int port, string query, TimeSpan? timeout, bool raw)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(host);
        ArgumentNullException.ThrowIfNull(query);
        if (port is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(port));
        TimeSpan budget = timeout ?? TimeSpan.FromSeconds(5);
        if (budget.TotalMilliseconds < 1 || budget.TotalMilliseconds > int.MaxValue)
            throw new ArgumentOutOfRangeException(nameof(timeout), "Timeout must be between 1 and 2147483647 milliseconds");
        if (query.Contains('\0')) throw new ArgumentException("Query contains NUL", nameof(query));
        int prefix = query.StartsWith('?') ? 0 : 1;
        int size = Utf8.GetByteCount(query) + prefix;
        if (size > 65529) throw new ArgumentException("Query exceeds two-byte frame length", nameof(query));
        var request = new byte[size + 10];
        request[1] = 131;
        BinaryPrimitives.WriteUInt16BigEndian(request.AsSpan(2), (ushort)(size + 6));
        request[9] = (byte)'?';
        Utf8.GetBytes(query, request.AsSpan(9 + prefix));

        using var deadline = new CancellationTokenSource(budget);
        try
        {
            IPAddress[] addresses = IPAddress.TryParse(host, out var address)
                ? [address] : await Dns.GetHostAddressesAsync(host, deadline.Token).ConfigureAwait(false);
            using var client = await ConnectAsync(addresses, port, deadline.Token).ConfigureAwait(false);
            using var stream = client.GetStream();
            await stream.WriteAsync(request, deadline.Token).ConfigureAwait(false);
            var header = new byte[4];
            await stream.ReadExactlyAsync(header, deadline.Token).ConfigureAwait(false);
            if (header[0] != 0 || header[1] != 131) throw new InvalidDataException("Non-Topic response");
            int length = BinaryPrimitives.ReadUInt16BigEndian(header.AsSpan(2));
            if (length == 0) throw new InvalidDataException("Empty Topic body");
            var body = new byte[length];
            await stream.ReadExactlyAsync(body, deadline.Token).ConfigureAwait(false);
            return body[0] switch
            {
                0 when length == 1 => null,
                6 when length >= 2 && body[^1] == 0 => raw ? body[1..^1] : DecodeText(body.AsSpan(1, length - 2)),
                42 when length == 5 => BinaryPrimitives.ReadSingleLittleEndian(body.AsSpan(1)),
                _ => throw new InvalidDataException("Invalid Topic response")
            };
        }
        catch (OperationCanceledException error) when (deadline.IsCancellationRequested)
        {
            throw new TimeoutException("Topic request timed out", error);
        }
    }

    internal static async Task<TcpClient> ConnectAsync(IPAddress[] addresses, int port, CancellationToken token)
    {
        SocketException? last = null;
        foreach (var endpoint in addresses)
        {
            token.ThrowIfCancellationRequested();
            TcpClient? client = null;
            try
            {
                client = new TcpClient(endpoint.AddressFamily);
                await client.ConnectAsync(endpoint, port, token).ConfigureAwait(false);
                return client;
            }
            catch (SocketException error) { client?.Dispose(); last = error; }
            catch { client?.Dispose(); throw; }
        }
        throw last ?? new SocketException((int)SocketError.HostNotFound);
    }
}
