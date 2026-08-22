#![allow(clippy::redundant_closure_call)]
#![allow(clippy::needless_lifetimes)]
#![allow(clippy::match_single_binding)]
#![allow(clippy::clone_on_copy)]

#[doc = r" Error types."]
pub mod error {
    #[doc = r" Error from a `TryFrom` or `FromStr` implementation."]
    pub struct ConversionError(::std::borrow::Cow<'static, str>);
    impl ::std::error::Error for ConversionError {}
    impl ::std::fmt::Display for ConversionError {
        fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> Result<(), ::std::fmt::Error> {
            ::std::fmt::Display::fmt(&self.0, f)
        }
    }
    impl ::std::fmt::Debug for ConversionError {
        fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> Result<(), ::std::fmt::Error> {
            ::std::fmt::Debug::fmt(&self.0, f)
        }
    }
    impl From<&'static str> for ConversionError {
        fn from(value: &'static str) -> Self {
            Self(value.into())
        }
    }
    impl From<String> for ConversionError {
        fn from(value: String) -> Self {
            Self(value.into())
        }
    }
}
#[doc = "`DescribeResult`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"methods\","]
#[doc = "    \"protocol_version\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"methods\": {"]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"$ref\": \"#/$defs/PlatformMethod\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"protocol_version\": {"]
#[doc = "      \"$ref\": \"#/$defs/ProtocolVersion\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct DescribeResult {
    pub methods: ::std::vec::Vec<PlatformMethod>,
    pub protocol_version: ProtocolVersion,
}
impl DescribeResult {
    pub fn builder() -> builder::DescribeResult {
        Default::default()
    }
}
#[doc = "platform.http params.request — one webview API call crossing boundary E."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"description\": \"platform.http params.request — one webview API call crossing boundary E.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"body_base64\","]
#[doc = "    \"method\","]
#[doc = "    \"path\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"body_base64\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"method\": {"]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"enum\": ["]
#[doc = "        \"GET\","]
#[doc = "        \"POST\","]
#[doc = "        \"PUT\","]
#[doc = "        \"DELETE\","]
#[doc = "        \"PATCH\","]
#[doc = "        \"HEAD\","]
#[doc = "        \"OPTIONS\""]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"path\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct HttpRequest {
    pub body_base64: ::std::string::String,
    pub method: HttpRequestMethod,
    pub path: ::std::string::String,
}
impl HttpRequest {
    pub fn builder() -> builder::HttpRequest {
        Default::default()
    }
}
#[doc = "`HttpRequestMethod`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"GET\","]
#[doc = "    \"POST\","]
#[doc = "    \"PUT\","]
#[doc = "    \"DELETE\","]
#[doc = "    \"PATCH\","]
#[doc = "    \"HEAD\","]
#[doc = "    \"OPTIONS\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum HttpRequestMethod {
    #[serde(rename = "GET")]
    Get,
    #[serde(rename = "POST")]
    Post,
    #[serde(rename = "PUT")]
    Put,
    #[serde(rename = "DELETE")]
    Delete,
    #[serde(rename = "PATCH")]
    Patch,
    #[serde(rename = "HEAD")]
    Head,
    #[serde(rename = "OPTIONS")]
    Options,
}
impl ::std::fmt::Display for HttpRequestMethod {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Get => f.write_str("GET"),
            Self::Post => f.write_str("POST"),
            Self::Put => f.write_str("PUT"),
            Self::Delete => f.write_str("DELETE"),
            Self::Patch => f.write_str("PATCH"),
            Self::Head => f.write_str("HEAD"),
            Self::Options => f.write_str("OPTIONS"),
        }
    }
}
impl ::std::str::FromStr for HttpRequestMethod {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "GET" => Ok(Self::Get),
            "POST" => Ok(Self::Post),
            "PUT" => Ok(Self::Put),
            "DELETE" => Ok(Self::Delete),
            "PATCH" => Ok(Self::Patch),
            "HEAD" => Ok(Self::Head),
            "OPTIONS" => Ok(Self::Options),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for HttpRequestMethod {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for HttpRequestMethod {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for HttpRequestMethod {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "platform.http result — status, media type, and base64 body."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"description\": \"platform.http result — status, media type, and base64 body.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"body_base64\","]
#[doc = "    \"content_type\","]
#[doc = "    \"status\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"body_base64\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"content_type\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"status\": {"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 599.0,"]
#[doc = "      \"minimum\": 100.0"]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct HttpResult {
    pub body_base64: ::std::string::String,
    pub content_type: ::std::string::String,
    pub status: i64,
}
impl HttpResult {
    pub fn builder() -> builder::HttpResult {
        Default::default()
    }
}
#[doc = "`PingResult`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"node_version\","]
#[doc = "    \"ok\","]
#[doc = "    \"pid\","]
#[doc = "    \"protocol_version\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"node_version\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"ok\": {"]
#[doc = "      \"type\": \"boolean\","]
#[doc = "      \"enum\": ["]
#[doc = "        true"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"pid\": {"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": 0.0"]
#[doc = "    },"]
#[doc = "    \"protocol_version\": {"]
#[doc = "      \"$ref\": \"#/$defs/ProtocolVersion\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct PingResult {
    pub node_version: ::std::string::String,
    pub ok: bool,
    pub pid: i64,
    pub protocol_version: ProtocolVersion,
}
impl PingResult {
    pub fn builder() -> builder::PingResult {
        Default::default()
    }
}
#[doc = "`PlatformError`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"code\","]
#[doc = "    \"diagnostic_id\","]
#[doc = "    \"message\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"code\": {"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"data\": {"]
#[doc = "      \"type\": \"object\""]
#[doc = "    },"]
#[doc = "    \"diagnostic_id\": {"]
#[doc = "      \"description\": \"L15.3: every surfaced failure carries an id a human can quote and a log can find.\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"message\": {"]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"reason_code\": {"]
#[doc = "      \"$ref\": \"#/$defs/ReasonCode\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct PlatformError {
    pub code: i32,
    #[serde(default, skip_serializing_if = "::serde_json::Map::is_empty")]
    pub data: ::serde_json::Map<::std::string::String, ::serde_json::Value>,
    #[doc = "L15.3: every surfaced failure carries an id a human can quote and a log can find."]
    pub diagnostic_id: ::std::string::String,
    pub message: ::std::string::String,
    #[serde(default, skip_serializing_if = "::std::option::Option::is_none")]
    pub reason_code: ::std::option::Option<ReasonCode>,
}
impl PlatformError {
    pub fn builder() -> builder::PlatformError {
        Default::default()
    }
}
#[doc = "Every method that may cross boundary E. C5 extends this list."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"description\": \"Every method that may cross boundary E. C5 extends this list.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"platform.ping\","]
#[doc = "    \"platform.describe\","]
#[doc = "    \"platform.shutdown\","]
#[doc = "    \"platform.http\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum PlatformMethod {
    #[serde(rename = "platform.ping")]
    PlatformPing,
    #[serde(rename = "platform.describe")]
    PlatformDescribe,
    #[serde(rename = "platform.shutdown")]
    PlatformShutdown,
    #[serde(rename = "platform.http")]
    PlatformHttp,
}
impl ::std::fmt::Display for PlatformMethod {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::PlatformPing => f.write_str("platform.ping"),
            Self::PlatformDescribe => f.write_str("platform.describe"),
            Self::PlatformShutdown => f.write_str("platform.shutdown"),
            Self::PlatformHttp => f.write_str("platform.http"),
        }
    }
}
impl ::std::str::FromStr for PlatformMethod {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "platform.ping" => Ok(Self::PlatformPing),
            "platform.describe" => Ok(Self::PlatformDescribe),
            "platform.shutdown" => Ok(Self::PlatformShutdown),
            "platform.http" => Ok(Self::PlatformHttp),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for PlatformMethod {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for PlatformMethod {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for PlatformMethod {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`PlatformRequest`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"id\","]
#[doc = "    \"jsonrpc\","]
#[doc = "    \"method\","]
#[doc = "    \"params\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"id\": {"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": 0.0"]
#[doc = "    },"]
#[doc = "    \"jsonrpc\": {"]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"enum\": ["]
#[doc = "        \"2.0\""]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"method\": {"]
#[doc = "      \"$ref\": \"#/$defs/PlatformMethod\""]
#[doc = "    },"]
#[doc = "    \"params\": {"]
#[doc = "      \"type\": \"object\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct PlatformRequest {
    pub id: i64,
    pub jsonrpc: PlatformRequestJsonrpc,
    pub method: PlatformMethod,
    pub params: ::serde_json::Map<::std::string::String, ::serde_json::Value>,
}
impl PlatformRequest {
    pub fn builder() -> builder::PlatformRequest {
        Default::default()
    }
}
#[doc = "`PlatformRequestJsonrpc`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"2.0\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum PlatformRequestJsonrpc {
    #[serde(rename = "2.0")]
    X20,
}
impl ::std::fmt::Display for PlatformRequestJsonrpc {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::X20 => f.write_str("2.0"),
        }
    }
}
impl ::std::str::FromStr for PlatformRequestJsonrpc {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "2.0" => Ok(Self::X20),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for PlatformRequestJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for PlatformRequestJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for PlatformRequestJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "Exactly ONE of result/error is present — stated in prose because a oneOf here produces hostile typify output; boundary-validate.mjs enforces it at runtime, both directions, in production."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"description\": \"Exactly ONE of result/error is present — stated in prose because a oneOf here produces hostile typify output; boundary-validate.mjs enforces it at runtime, both directions, in production.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"id\","]
#[doc = "    \"jsonrpc\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"error\": {"]
#[doc = "      \"$ref\": \"#/$defs/PlatformError\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": 0.0"]
#[doc = "    },"]
#[doc = "    \"jsonrpc\": {"]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"enum\": ["]
#[doc = "        \"2.0\""]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"result\": {"]
#[doc = "      \"type\": \"object\""]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct PlatformResponse {
    #[serde(default, skip_serializing_if = "::std::option::Option::is_none")]
    pub error: ::std::option::Option<PlatformError>,
    pub id: i64,
    pub jsonrpc: PlatformResponseJsonrpc,
    #[serde(default, skip_serializing_if = "::serde_json::Map::is_empty")]
    pub result: ::serde_json::Map<::std::string::String, ::serde_json::Value>,
}
impl PlatformResponse {
    pub fn builder() -> builder::PlatformResponse {
        Default::default()
    }
}
#[doc = "`PlatformResponseJsonrpc`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"2.0\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum PlatformResponseJsonrpc {
    #[serde(rename = "2.0")]
    X20,
}
impl ::std::fmt::Display for PlatformResponseJsonrpc {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::X20 => f.write_str("2.0"),
        }
    }
}
impl ::std::str::FromStr for PlatformResponseJsonrpc {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "2.0" => Ok(Self::X20),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for PlatformResponseJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for PlatformResponseJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for PlatformResponseJsonrpc {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "Bumped only by a commit that regenerates every consumer."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"description\": \"Bumped only by a commit that regenerates every consumer.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"e1\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum ProtocolVersion {
    #[serde(rename = "e1")]
    E1,
}
impl ::std::fmt::Display for ProtocolVersion {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::E1 => f.write_str("e1"),
        }
    }
}
impl ::std::str::FromStr for ProtocolVersion {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "e1" => Ok(Self::E1),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ProtocolVersion {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for ProtocolVersion {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ProtocolVersion {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "Machine-readable blocking reasons attached to every UNPROVEN verdict (Law L2)."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"ReasonCode\","]
#[doc = "  \"description\": \"Machine-readable blocking reasons attached to every UNPROVEN verdict (Law L2).\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"TARGET_UNREACHABLE\","]
#[doc = "    \"ENV_REPRODUCTION_FAILED\","]
#[doc = "    \"HARNESS_SYNTHESIS_FAILED\","]
#[doc = "    \"SYNTHESIS_DECLINED\","]
#[doc = "    \"UNINTERCEPTABLE_EFFECT\","]
#[doc = "    \"NONDETERMINISTIC_BASE\","]
#[doc = "    \"SANDBOX_UNAVAILABLE\","]
#[doc = "    \"VALUE_UNSERIALIZABLE\","]
#[doc = "    \"RECORD_REPLAY_UNAVAILABLE\""]
#[doc = "  ]"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Deserialize,
    :: serde :: Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
)]
pub enum ReasonCode {
    #[serde(rename = "TARGET_UNREACHABLE")]
    TargetUnreachable,
    #[serde(rename = "ENV_REPRODUCTION_FAILED")]
    EnvReproductionFailed,
    #[serde(rename = "HARNESS_SYNTHESIS_FAILED")]
    HarnessSynthesisFailed,
    #[serde(rename = "SYNTHESIS_DECLINED")]
    SynthesisDeclined,
    #[serde(rename = "UNINTERCEPTABLE_EFFECT")]
    UninterceptableEffect,
    #[serde(rename = "NONDETERMINISTIC_BASE")]
    NondeterministicBase,
    #[serde(rename = "SANDBOX_UNAVAILABLE")]
    SandboxUnavailable,
    #[serde(rename = "VALUE_UNSERIALIZABLE")]
    ValueUnserializable,
    #[serde(rename = "RECORD_REPLAY_UNAVAILABLE")]
    RecordReplayUnavailable,
}
impl ::std::fmt::Display for ReasonCode {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::TargetUnreachable => f.write_str("TARGET_UNREACHABLE"),
            Self::EnvReproductionFailed => f.write_str("ENV_REPRODUCTION_FAILED"),
            Self::HarnessSynthesisFailed => f.write_str("HARNESS_SYNTHESIS_FAILED"),
            Self::SynthesisDeclined => f.write_str("SYNTHESIS_DECLINED"),
            Self::UninterceptableEffect => f.write_str("UNINTERCEPTABLE_EFFECT"),
            Self::NondeterministicBase => f.write_str("NONDETERMINISTIC_BASE"),
            Self::SandboxUnavailable => f.write_str("SANDBOX_UNAVAILABLE"),
            Self::ValueUnserializable => f.write_str("VALUE_UNSERIALIZABLE"),
            Self::RecordReplayUnavailable => f.write_str("RECORD_REPLAY_UNAVAILABLE"),
        }
    }
}
impl ::std::str::FromStr for ReasonCode {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "TARGET_UNREACHABLE" => Ok(Self::TargetUnreachable),
            "ENV_REPRODUCTION_FAILED" => Ok(Self::EnvReproductionFailed),
            "HARNESS_SYNTHESIS_FAILED" => Ok(Self::HarnessSynthesisFailed),
            "SYNTHESIS_DECLINED" => Ok(Self::SynthesisDeclined),
            "UNINTERCEPTABLE_EFFECT" => Ok(Self::UninterceptableEffect),
            "NONDETERMINISTIC_BASE" => Ok(Self::NondeterministicBase),
            "SANDBOX_UNAVAILABLE" => Ok(Self::SandboxUnavailable),
            "VALUE_UNSERIALIZABLE" => Ok(Self::ValueUnserializable),
            "RECORD_REPLAY_UNAVAILABLE" => Ok(Self::RecordReplayUnavailable),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ReasonCode {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for ReasonCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ReasonCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`ShutdownResult`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"ok\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"ok\": {"]
#[doc = "      \"type\": \"boolean\","]
#[doc = "      \"enum\": ["]
#[doc = "        true"]
#[doc = "      ]"]
#[doc = "    }"]
#[doc = "  },"]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct ShutdownResult {
    pub ok: bool,
}
impl ShutdownResult {
    pub fn builder() -> builder::ShutdownResult {
        Default::default()
    }
}
#[doc = "Boundary E (Rust host <-> Node platform sidecar), JSON-RPC 2.0 over a Unix domain socket with Content-Length framing. Generated — do not edit; run `make gen-contracts`."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"TempestPlatformBoundary\","]
#[doc = "  \"description\": \"Boundary E (Rust host <-> Node platform sidecar), JSON-RPC 2.0 over a Unix domain socket with Content-Length framing. Generated — do not edit; run `make gen-contracts`.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct TempestPlatformBoundary {}
impl ::std::default::Default for TempestPlatformBoundary {
    fn default() -> Self {
        Self {}
    }
}
impl TempestPlatformBoundary {
    pub fn builder() -> builder::TempestPlatformBoundary {
        Default::default()
    }
}
#[doc = r" Types for composing complex structures."]
pub mod builder {
    #[derive(Clone, Debug)]
    pub struct DescribeResult {
        methods:
            ::std::result::Result<::std::vec::Vec<super::PlatformMethod>, ::std::string::String>,
        protocol_version: ::std::result::Result<super::ProtocolVersion, ::std::string::String>,
    }
    impl ::std::default::Default for DescribeResult {
        fn default() -> Self {
            Self {
                methods: Err("no value supplied for methods".to_string()),
                protocol_version: Err("no value supplied for protocol_version".to_string()),
            }
        }
    }
    impl DescribeResult {
        pub fn methods<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<super::PlatformMethod>>,
            T::Error: ::std::fmt::Display,
        {
            self.methods = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for methods: {e}"));
            self
        }
        pub fn protocol_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::ProtocolVersion>,
            T::Error: ::std::fmt::Display,
        {
            self.protocol_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for protocol_version: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<DescribeResult> for super::DescribeResult {
        type Error = super::error::ConversionError;
        fn try_from(
            value: DescribeResult,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                methods: value.methods?,
                protocol_version: value.protocol_version?,
            })
        }
    }
    impl ::std::convert::From<super::DescribeResult> for DescribeResult {
        fn from(value: super::DescribeResult) -> Self {
            Self {
                methods: Ok(value.methods),
                protocol_version: Ok(value.protocol_version),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct HttpRequest {
        body_base64: ::std::result::Result<::std::string::String, ::std::string::String>,
        method: ::std::result::Result<super::HttpRequestMethod, ::std::string::String>,
        path: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for HttpRequest {
        fn default() -> Self {
            Self {
                body_base64: Err("no value supplied for body_base64".to_string()),
                method: Err("no value supplied for method".to_string()),
                path: Err("no value supplied for path".to_string()),
            }
        }
    }
    impl HttpRequest {
        pub fn body_base64<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.body_base64 = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for body_base64: {e}"));
            self
        }
        pub fn method<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::HttpRequestMethod>,
            T::Error: ::std::fmt::Display,
        {
            self.method = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for method: {e}"));
            self
        }
        pub fn path<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.path = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for path: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<HttpRequest> for super::HttpRequest {
        type Error = super::error::ConversionError;
        fn try_from(
            value: HttpRequest,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                body_base64: value.body_base64?,
                method: value.method?,
                path: value.path?,
            })
        }
    }
    impl ::std::convert::From<super::HttpRequest> for HttpRequest {
        fn from(value: super::HttpRequest) -> Self {
            Self {
                body_base64: Ok(value.body_base64),
                method: Ok(value.method),
                path: Ok(value.path),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct HttpResult {
        body_base64: ::std::result::Result<::std::string::String, ::std::string::String>,
        content_type: ::std::result::Result<::std::string::String, ::std::string::String>,
        status: ::std::result::Result<i64, ::std::string::String>,
    }
    impl ::std::default::Default for HttpResult {
        fn default() -> Self {
            Self {
                body_base64: Err("no value supplied for body_base64".to_string()),
                content_type: Err("no value supplied for content_type".to_string()),
                status: Err("no value supplied for status".to_string()),
            }
        }
    }
    impl HttpResult {
        pub fn body_base64<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.body_base64 = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for body_base64: {e}"));
            self
        }
        pub fn content_type<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.content_type = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for content_type: {e}"));
            self
        }
        pub fn status<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i64>,
            T::Error: ::std::fmt::Display,
        {
            self.status = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for status: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<HttpResult> for super::HttpResult {
        type Error = super::error::ConversionError;
        fn try_from(
            value: HttpResult,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                body_base64: value.body_base64?,
                content_type: value.content_type?,
                status: value.status?,
            })
        }
    }
    impl ::std::convert::From<super::HttpResult> for HttpResult {
        fn from(value: super::HttpResult) -> Self {
            Self {
                body_base64: Ok(value.body_base64),
                content_type: Ok(value.content_type),
                status: Ok(value.status),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct PingResult {
        node_version: ::std::result::Result<::std::string::String, ::std::string::String>,
        ok: ::std::result::Result<bool, ::std::string::String>,
        pid: ::std::result::Result<i64, ::std::string::String>,
        protocol_version: ::std::result::Result<super::ProtocolVersion, ::std::string::String>,
    }
    impl ::std::default::Default for PingResult {
        fn default() -> Self {
            Self {
                node_version: Err("no value supplied for node_version".to_string()),
                ok: Err("no value supplied for ok".to_string()),
                pid: Err("no value supplied for pid".to_string()),
                protocol_version: Err("no value supplied for protocol_version".to_string()),
            }
        }
    }
    impl PingResult {
        pub fn node_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.node_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for node_version: {e}"));
            self
        }
        pub fn ok<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<bool>,
            T::Error: ::std::fmt::Display,
        {
            self.ok = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for ok: {e}"));
            self
        }
        pub fn pid<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i64>,
            T::Error: ::std::fmt::Display,
        {
            self.pid = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for pid: {e}"));
            self
        }
        pub fn protocol_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::ProtocolVersion>,
            T::Error: ::std::fmt::Display,
        {
            self.protocol_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for protocol_version: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<PingResult> for super::PingResult {
        type Error = super::error::ConversionError;
        fn try_from(
            value: PingResult,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                node_version: value.node_version?,
                ok: value.ok?,
                pid: value.pid?,
                protocol_version: value.protocol_version?,
            })
        }
    }
    impl ::std::convert::From<super::PingResult> for PingResult {
        fn from(value: super::PingResult) -> Self {
            Self {
                node_version: Ok(value.node_version),
                ok: Ok(value.ok),
                pid: Ok(value.pid),
                protocol_version: Ok(value.protocol_version),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct PlatformError {
        code: ::std::result::Result<i32, ::std::string::String>,
        data: ::std::result::Result<
            ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            ::std::string::String,
        >,
        diagnostic_id: ::std::result::Result<::std::string::String, ::std::string::String>,
        message: ::std::result::Result<::std::string::String, ::std::string::String>,
        reason_code:
            ::std::result::Result<::std::option::Option<super::ReasonCode>, ::std::string::String>,
    }
    impl ::std::default::Default for PlatformError {
        fn default() -> Self {
            Self {
                code: Err("no value supplied for code".to_string()),
                data: Ok(Default::default()),
                diagnostic_id: Err("no value supplied for diagnostic_id".to_string()),
                message: Err("no value supplied for message".to_string()),
                reason_code: Ok(Default::default()),
            }
        }
    }
    impl PlatformError {
        pub fn code<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.code = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for code: {e}"));
            self
        }
        pub fn data<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<
                ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            >,
            T::Error: ::std::fmt::Display,
        {
            self.data = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for data: {e}"));
            self
        }
        pub fn diagnostic_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.diagnostic_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for diagnostic_id: {e}"));
            self
        }
        pub fn message<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.message = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for message: {e}"));
            self
        }
        pub fn reason_code<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<super::ReasonCode>>,
            T::Error: ::std::fmt::Display,
        {
            self.reason_code = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for reason_code: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<PlatformError> for super::PlatformError {
        type Error = super::error::ConversionError;
        fn try_from(
            value: PlatformError,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                code: value.code?,
                data: value.data?,
                diagnostic_id: value.diagnostic_id?,
                message: value.message?,
                reason_code: value.reason_code?,
            })
        }
    }
    impl ::std::convert::From<super::PlatformError> for PlatformError {
        fn from(value: super::PlatformError) -> Self {
            Self {
                code: Ok(value.code),
                data: Ok(value.data),
                diagnostic_id: Ok(value.diagnostic_id),
                message: Ok(value.message),
                reason_code: Ok(value.reason_code),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct PlatformRequest {
        id: ::std::result::Result<i64, ::std::string::String>,
        jsonrpc: ::std::result::Result<super::PlatformRequestJsonrpc, ::std::string::String>,
        method: ::std::result::Result<super::PlatformMethod, ::std::string::String>,
        params: ::std::result::Result<
            ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            ::std::string::String,
        >,
    }
    impl ::std::default::Default for PlatformRequest {
        fn default() -> Self {
            Self {
                id: Err("no value supplied for id".to_string()),
                jsonrpc: Err("no value supplied for jsonrpc".to_string()),
                method: Err("no value supplied for method".to_string()),
                params: Err("no value supplied for params".to_string()),
            }
        }
    }
    impl PlatformRequest {
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i64>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn jsonrpc<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::PlatformRequestJsonrpc>,
            T::Error: ::std::fmt::Display,
        {
            self.jsonrpc = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for jsonrpc: {e}"));
            self
        }
        pub fn method<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::PlatformMethod>,
            T::Error: ::std::fmt::Display,
        {
            self.method = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for method: {e}"));
            self
        }
        pub fn params<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<
                ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            >,
            T::Error: ::std::fmt::Display,
        {
            self.params = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for params: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<PlatformRequest> for super::PlatformRequest {
        type Error = super::error::ConversionError;
        fn try_from(
            value: PlatformRequest,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                id: value.id?,
                jsonrpc: value.jsonrpc?,
                method: value.method?,
                params: value.params?,
            })
        }
    }
    impl ::std::convert::From<super::PlatformRequest> for PlatformRequest {
        fn from(value: super::PlatformRequest) -> Self {
            Self {
                id: Ok(value.id),
                jsonrpc: Ok(value.jsonrpc),
                method: Ok(value.method),
                params: Ok(value.params),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct PlatformResponse {
        error: ::std::result::Result<
            ::std::option::Option<super::PlatformError>,
            ::std::string::String,
        >,
        id: ::std::result::Result<i64, ::std::string::String>,
        jsonrpc: ::std::result::Result<super::PlatformResponseJsonrpc, ::std::string::String>,
        result: ::std::result::Result<
            ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            ::std::string::String,
        >,
    }
    impl ::std::default::Default for PlatformResponse {
        fn default() -> Self {
            Self {
                error: Ok(Default::default()),
                id: Err("no value supplied for id".to_string()),
                jsonrpc: Err("no value supplied for jsonrpc".to_string()),
                result: Ok(Default::default()),
            }
        }
    }
    impl PlatformResponse {
        pub fn error<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<super::PlatformError>>,
            T::Error: ::std::fmt::Display,
        {
            self.error = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for error: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i64>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn jsonrpc<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::PlatformResponseJsonrpc>,
            T::Error: ::std::fmt::Display,
        {
            self.jsonrpc = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for jsonrpc: {e}"));
            self
        }
        pub fn result<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<
                ::serde_json::Map<::std::string::String, ::serde_json::Value>,
            >,
            T::Error: ::std::fmt::Display,
        {
            self.result = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for result: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<PlatformResponse> for super::PlatformResponse {
        type Error = super::error::ConversionError;
        fn try_from(
            value: PlatformResponse,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                error: value.error?,
                id: value.id?,
                jsonrpc: value.jsonrpc?,
                result: value.result?,
            })
        }
    }
    impl ::std::convert::From<super::PlatformResponse> for PlatformResponse {
        fn from(value: super::PlatformResponse) -> Self {
            Self {
                error: Ok(value.error),
                id: Ok(value.id),
                jsonrpc: Ok(value.jsonrpc),
                result: Ok(value.result),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct ShutdownResult {
        ok: ::std::result::Result<bool, ::std::string::String>,
    }
    impl ::std::default::Default for ShutdownResult {
        fn default() -> Self {
            Self {
                ok: Err("no value supplied for ok".to_string()),
            }
        }
    }
    impl ShutdownResult {
        pub fn ok<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<bool>,
            T::Error: ::std::fmt::Display,
        {
            self.ok = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for ok: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<ShutdownResult> for super::ShutdownResult {
        type Error = super::error::ConversionError;
        fn try_from(
            value: ShutdownResult,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self { ok: value.ok? })
        }
    }
    impl ::std::convert::From<super::ShutdownResult> for ShutdownResult {
        fn from(value: super::ShutdownResult) -> Self {
            Self { ok: Ok(value.ok) }
        }
    }
    #[derive(Clone, Debug)]
    pub struct TempestPlatformBoundary {}
    impl ::std::default::Default for TempestPlatformBoundary {
        fn default() -> Self {
            Self {}
        }
    }
    impl TempestPlatformBoundary {}
    impl ::std::convert::TryFrom<TempestPlatformBoundary> for super::TempestPlatformBoundary {
        type Error = super::error::ConversionError;
        fn try_from(
            _value: TempestPlatformBoundary,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {})
        }
    }
    impl ::std::convert::From<super::TempestPlatformBoundary> for TempestPlatformBoundary {
        fn from(_value: super::TempestPlatformBoundary) -> Self {
            Self {}
        }
    }
}
