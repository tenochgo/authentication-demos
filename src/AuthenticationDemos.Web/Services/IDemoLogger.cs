namespace AuthenticationDemos.Web.Services;

public enum LogLevel
{
    Info,
    Warning,
    Error,
    Token,
    Claim
}

public class LogEntry
{
    public DateTime Timestamp { get; set; }
    public LogLevel Level { get; set; }
    public string Message { get; set; } = string.Empty;
}

public interface IDemoLogger
{
    IReadOnlyList<LogEntry> Entries { get; }
    event Action<LogEntry>? OnLogEntry;
    void Log(LogLevel level, string message);
    void Clear();
}
