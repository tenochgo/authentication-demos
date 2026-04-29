using AuthenticationDemos.Web.Models;

namespace AuthenticationDemos.Web.Services;

public interface IStorageExplorer
{
    Task<List<string>> ListContainersAsync();
    Task<List<BlobItemModel>> ListBlobsAsync(string containerName, string? prefix = null);
}
