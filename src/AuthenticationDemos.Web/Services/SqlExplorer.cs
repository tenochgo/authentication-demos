using AuthenticationDemos.Web.Models;
using Microsoft.Data.SqlClient;

namespace AuthenticationDemos.Web.Services;

public class SqlExplorer : ISqlExplorer
{
    private readonly string _connectionString;
    private readonly string _accessToken;
    private readonly IDemoLogger _logger;
    private List<SqlTableInfo>? _allowedTables;

    public SqlExplorer(string connectionString, string accessToken, IDemoLogger logger)
    {
        _connectionString = connectionString;
        _accessToken = accessToken;
        _logger = logger;
    }

    public async Task<List<SqlTableInfo>> ListTablesAsync()
    {
        _logger.Log(LogLevel.Info, "Querying INFORMATION_SCHEMA.TABLES to discover tables...");

        var tables = new List<SqlTableInfo>();

        try
        {
            using var connection = CreateConnection();
            await connection.OpenAsync();

            using var command = connection.CreateCommand();
            command.CommandText = @"
                SELECT TABLE_SCHEMA, TABLE_NAME 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_TYPE = 'BASE TABLE' 
                ORDER BY TABLE_SCHEMA, TABLE_NAME";

            using var reader = await command.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                tables.Add(new SqlTableInfo
                {
                    Schema = reader.GetString(0),
                    TableName = reader.GetString(1)
                });
            }

            _allowedTables = tables;
            _logger.Log(LogLevel.Info, $"Found {tables.Count} table(s): {string.Join(", ", tables.Select(t => t.FullName))}");
        }
        catch (Exception ex)
        {
            _logger.Log(LogLevel.Error, $"Error listing tables: {ex.Message}");
        }

        return tables;
    }

    public async Task<SqlQueryResult> ExecuteQueryAsync(SqlTableInfo table, int topN = 10)
    {
        // Cap topN to prevent abuse
        topN = Math.Clamp(topN, 1, 100);

        // Validate table against allowlist
        if (_allowedTables != null &&
            !_allowedTables.Any(t => t.Schema == table.Schema && t.TableName == table.TableName))
        {
            _logger.Log(LogLevel.Error, $"Table '{table.FullName}' is not in the allowed list. Aborting query.");
            return new SqlQueryResult();
        }

        _logger.Log(LogLevel.Info, $"Executing: SELECT TOP {topN} * FROM [{table.Schema}].[{table.TableName}]");

        var result = new SqlQueryResult();

        try
        {
            using var connection = CreateConnection();
            await connection.OpenAsync();

            using var command = connection.CreateCommand();
            // Schema and table names are validated against the allowlist above.
            // SqlCommand parameters cannot be used for identifiers, so we use
            // bracket-quoted names after allowlist validation.
            command.CommandText = $"SELECT TOP (@topN) * FROM [{table.Schema}].[{table.TableName}]";
            command.Parameters.AddWithValue("@topN", topN);

            using var reader = await command.ExecuteReaderAsync();

            for (int i = 0; i < reader.FieldCount; i++)
            {
                result.Columns.Add(reader.GetName(i));
            }

            while (await reader.ReadAsync())
            {
                var row = new Dictionary<string, object?>();
                for (int i = 0; i < reader.FieldCount; i++)
                {
                    row[reader.GetName(i)] = reader.IsDBNull(i) ? null : reader.GetValue(i);
                }
                result.Rows.Add(row);
            }

            _logger.Log(LogLevel.Info, $"Query returned {result.Rows.Count} row(s) with {result.Columns.Count} column(s)");
        }
        catch (Exception ex)
        {
            _logger.Log(LogLevel.Error, $"Error executing query: {ex.Message}");
        }

        return result;
    }

    private SqlConnection CreateConnection()
    {
        var connection = new SqlConnection(_connectionString);
        connection.AccessToken = _accessToken;
        return connection;
    }
}
