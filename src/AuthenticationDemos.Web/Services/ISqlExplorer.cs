using AuthenticationDemos.Web.Models;

namespace AuthenticationDemos.Web.Services;

public interface ISqlExplorer
{
    Task<List<SqlTableInfo>> ListTablesAsync();
    Task<SqlQueryResult> ExecuteQueryAsync(SqlTableInfo table, int topN = 10);
}
