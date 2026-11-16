using System.ComponentModel;
using System.Windows.Controls;

namespace BandcampDownloader
{
    public enum TagEditAction
    {
        [Description("Do not modify")]
        DoNotModify,
        [Description("Save in tag")]
        Modify,
    }

    public class DoubleRule : ValidationRule
    {
        public override ValidationResult Validate(object value, System.Globalization.CultureInfo culture)
        {
            return new ValidationResult(false, "Not a numeric value");
        }
    }

    public class DownloadManager
    {
        public void Report(string album)
        {
            DownloadProgressChanged?.Invoke(this, new DownloadProgressChangedArgs($"Finished downloading album \"{album}\"", DownloadProgressChangedLevel.Success));
            var key = new ConfigKeyArgs("download_folder");
        }
    }
}
