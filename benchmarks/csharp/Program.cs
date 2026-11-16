using System.Diagnostics;
using System.Globalization;
using System.Text;
using ByondWire;

while (Console.ReadLine() is string line)
{
    var fields = line.Split('\t');
    var watch = Stopwatch.StartNew();
    try
    {
        object? value = fields[0] == "raw"
            ? await Client.TopicRawAsync(args[0], int.Parse(args[1]), fields[1])
            : await Client.TopicAsync(args[0], int.Parse(args[1]), fields[1]);
        watch.Stop();
        string kind = value is null ? "null" : value is float ? "number" : "text";
        if (kind == "text" && (fields[0] == "raw" ? value is not byte[] : value is not string)) throw new Exception("Incorrect native text type");
        int size = value switch { null => 0, float => 4, byte[] b => b.Length, string s => Encoding.UTF8.GetByteCount(s), _ => throw new Exception("Unexpected result type") };
        Console.WriteLine($"{watch.Elapsed.TotalMilliseconds.ToString(CultureInfo.InvariantCulture)}\t{kind}\t{size}");
    }
    catch (Exception error)
    {
        watch.Stop();
        Console.WriteLine($"{watch.Elapsed.TotalMilliseconds.ToString(CultureInfo.InvariantCulture)}\terror\t{error.GetType().Name}: {error.Message.Replace('\n', ' ').Replace('\r', ' ')}");
    }
}
