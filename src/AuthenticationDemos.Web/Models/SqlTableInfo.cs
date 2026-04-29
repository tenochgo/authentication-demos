namespace AuthenticationDemos.Web.Models;

public class SqlTableInfo
{
    public string Schema { get; set; } = string.Empty;
    public string TableName { get; set; } = string.Empty;

    public string FullName => $"{Schema}.{TableName}";
}
