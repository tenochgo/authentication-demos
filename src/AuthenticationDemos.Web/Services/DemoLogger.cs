namespace AuthenticationDemos.Web.Services;

public class DemoLogger : IDemoLogger
{
    private readonly List<LogEntry> _entries = new();
    private readonly object _lock = new();

    public IReadOnlyList<LogEntry> Entries
    {
        get
        {
            lock (_lock)
            {
                return _entries.ToList().AsReadOnly();
            }
        }
    }

    public event Action<LogEntry>? OnLogEntry;

    public void Log(LogLevel level, string message)
    {
        var entry = new LogEntry
        {
            Timestamp = DateTime.UtcNow,
            Level = level,
            Message = message
        };

        lock (_lock)
        {
            _entries.Add(entry);
        }

        OnLogEntry?.Invoke(entry);
    }

    public void Clear()
    {
        lock (_lock)
        {
            _entries.Clear();
        }
    }
}
