namespace AuthenticationDemos.Web.Models;

public class BlobItemModel
{
    public string Name { get; set; } = string.Empty;
    public bool IsFolder { get; set; }
    public long? Size { get; set; }
    public DateTimeOffset? LastModified { get; set; }
}
