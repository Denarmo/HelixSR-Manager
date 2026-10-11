namespace System.Web.Script.Serialization
{
    public class JavaScriptSerializer
    {
        public string Serialize(object obj) => "{}";
        public T Deserialize<T>(string input) => default;
    }
}
