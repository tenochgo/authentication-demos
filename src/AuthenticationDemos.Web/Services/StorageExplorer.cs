using AuthenticationDemos.Web.Models;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;

namespace AuthenticationDemos.Web.Services;

public class StorageExplorer : IStorageExplorer
{
    private readonly BlobServiceClient _client;
    private readonly IDemoLogger _logger;

    public StorageExplorer(BlobServiceClient client, IDemoLogger logger)
    {
        _client = client;
        _logger = logger;
    }

    public async Task<List<string>> ListContainersAsync()
    {
        _logger.Log(LogLevel.Info, $"Listing containers in storage account: {_client.AccountName}");
        var containers = new List<string>();

        try
        {
            await foreach (var container in _client.GetBlobContainersAsync())
            {
                containers.Add(container.Name);
            }

            _logger.Log(LogLevel.Info, $"Found {containers.Count} container(s): {string.Join(", ", containers)}");
        }
        catch (Exception ex)
        {
            _logger.Log(LogLevel.Error, $"Error listing containers: {ex.Message}");
        }

        return containers;
    }

    public async Task<List<BlobItemModel>> ListBlobsAsync(string containerName, string? prefix = null)
    {
        _logger.Log(LogLevel.Info, $"Listing blobs in container '{containerName}'" +
            (prefix != null ? $" with prefix '{prefix}'" : ""));

        var items = new List<BlobItemModel>();

        try
        {
            var containerClient = _client.GetBlobContainerClient(containerName);
            var resultSegment = containerClient.GetBlobsByHierarchyAsync(
                traits: BlobTraits.None,
                states: BlobStates.None,
                delimiter: "/",
                prefix: prefix,
                cancellationToken: default);

            await foreach (var item in resultSegment)
            {
                if (item.IsPrefix)
                {
                    items.Add(new BlobItemModel
                    {
                        Name = item.Prefix,
                        IsFolder = true
                    });
                }
                else if (item.IsBlob)
                {
                    items.Add(new BlobItemModel
                    {
                        Name = item.Blob.Name,
                        IsFolder = false,
                        Size = item.Blob.Properties.ContentLength,
                        LastModified = item.Blob.Properties.LastModified
                    });
                }
            }

            _logger.Log(LogLevel.Info, $"Found {items.Count} item(s)" +
                (prefix != null ? $" under '{prefix}'" : " at root"));
        }
        catch (Exception ex)
        {
            _logger.Log(LogLevel.Error, $"Error listing blobs: {ex.Message}");
        }

        return items;
    }
}
