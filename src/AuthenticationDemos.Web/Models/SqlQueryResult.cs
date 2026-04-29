namespace AuthenticationDemos.Web.Models;

public class SqlQueryResult
{
    public List<string> Columns { get; set; } = new();
    public List<Dictionary<string, object?>> Rows { get; set; } = new();
}
