using System.Globalization;
using System.Net.Sockets;
using System.Text;
using ByondWire;

try
{
    if (args.Length != 3 || !int.TryParse(args[1], NumberStyles.None, CultureInfo.InvariantCulture, out int port))
        throw new ArgumentException("Usage: byond-wire <address> <port> <message>");
    object? result = await Client.TopicRawAsync(args[0], port, args[2]);
    if (result is null) return 2;
    byte[] output = result is byte[] bytes ? bytes :
        Encoding.ASCII.GetBytes(((float)result).ToString("G9", CultureInfo.InvariantCulture));
    using var stdout = Console.OpenStandardOutput();
    await stdout.WriteAsync(output);
    return 0;
}
catch (TimeoutException)
{
    Console.Error.WriteLine("Topic request timed out");
    return 124;
}
catch (Exception error) when (error is ArgumentException or IOException or InvalidDataException or SocketException)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
