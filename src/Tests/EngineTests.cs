using System;
using NUnit.Framework;
using HelixSRSwapper;

namespace HelixSRManager.Tests
{
    [TestFixture]
    public class EngineTests
    {
        [Test]
        public void SetIniValue_NullText_ThrowsArgumentNullException()
        {
            Assert.Throws<ArgumentNullException>(() => Engine.SetIniValue(null, "Key", "Value", "Section"));
        }

        [Test]
        public void SetIniValue_NullKey_ThrowsArgumentNullException()
        {
            Assert.Throws<ArgumentNullException>(() => Engine.SetIniValue("Text", null, "Value", "Section"));
        }

        [Test]
        public void SetIniValue_ExistingKey_ModifiesValue()
        {
            string actual = Engine.SetIniValue("SomeKey = OldValue\r\n", "SomeKey", "NewValue", "");
            Assert.AreEqual("SomeKey = NewValue\r\n", actual);
        }

        [Test]
        public void SetIniValue_ExistingKeyInSection_ModifiesValue()
        {
            string actual = Engine.SetIniValue("[Section]\r\nSomeKey = OldValue\r\n", "SomeKey", "NewValue", "Section");
            Assert.AreEqual("[Section]\r\nSomeKey = NewValue\r\n", actual);
        }

        [Test]
        public void SetIniValue_NewKeyInSection_AddsKey()
        {
            string actual = Engine.SetIniValue("[Section]\r\n", "SomeKey", "Value", "Section");
            Assert.AreEqual("[Section]\r\nSomeKey = Value\r\n", actual);
        }

        [Test]
        public void SetIniValue_NewSectionAndKey_AddsBoth()
        {
            string actual = Engine.SetIniValue("OldText", "SomeKey", "Value", "Section");
            Assert.AreEqual("OldText\r\n[Section]\r\nSomeKey = Value\r\n", actual);
        }

        [Test]
        public void SetIniValue_NoSection_AddsKeyAtEnd()
        {
            string actual = Engine.SetIniValue("OldText", "SomeKey", "Value", null);
            Assert.AreEqual("OldText\r\nSomeKey = Value\r\n", actual);
        }
    }
}
