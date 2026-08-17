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
#[doc = "`Base`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Base\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"maxLength\": 200,"]
#[doc = "  \"minLength\": 1"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct Base(::std::string::String);
impl ::std::ops::Deref for Base {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<Base> for ::std::string::String {
    fn from(value: Base) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for Base {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        if value.chars().count() > 200usize {
            return Err("longer than 200 characters".into());
        }
        if value.chars().count() < 1usize {
            return Err("shorter than 1 characters".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for Base {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Base {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Base {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for Base {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`BaseSha`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Base Sha\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"pattern\": \"^[0-9a-f]{40}$\""]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct BaseSha(::std::string::String);
impl ::std::ops::Deref for BaseSha {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<BaseSha> for ::std::string::String {
    fn from(value: BaseSha) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for BaseSha {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        static PATTERN: ::std::sync::LazyLock<::regress::Regex> =
            ::std::sync::LazyLock::new(|| ::regress::Regex::new("^[0-9a-f]{40}$").unwrap());
        if PATTERN.find(value).is_none() {
            return Err("doesn't match pattern \"^[0-9a-f]{40}$\"".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for BaseSha {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for BaseSha {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for BaseSha {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for BaseSha {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`BodyImportRunBundle`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Body_importRunBundle\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"file\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"file\": {"]
#[doc = "      \"title\": \"File\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"contentMediaType\": \"application/octet-stream\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct BodyImportRunBundle {
    pub file: ::std::string::String,
}
impl BodyImportRunBundle {
    pub fn builder() -> builder::BodyImportRunBundle {
        Default::default()
    }
}
#[doc = "`BundlePresenceRequest`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"BundlePresenceRequest\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"digests\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"digests\": {"]
#[doc = "      \"title\": \"Digests\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"type\": \"string\""]
#[doc = "      },"]
#[doc = "      \"maxItems\": 1000"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct BundlePresenceRequest {
    pub digests: ::std::vec::Vec<::std::string::String>,
}
impl BundlePresenceRequest {
    pub fn builder() -> builder::BundlePresenceRequest {
        Default::default()
    }
}
#[doc = "`BundlePresenceResponse`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"BundlePresenceResponse\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"missing\","]
#[doc = "    \"present\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"missing\": {"]
#[doc = "      \"title\": \"Missing\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"type\": \"string\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"present\": {"]
#[doc = "      \"title\": \"Present\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"type\": \"string\""]
#[doc = "      }"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct BundlePresenceResponse {
    pub missing: ::std::vec::Vec<::std::string::String>,
    pub present: ::std::vec::Vec<::std::string::String>,
}
impl BundlePresenceResponse {
    pub fn builder() -> builder::BundlePresenceResponse {
        Default::default()
    }
}
#[doc = "202 for cancelRun: children are already signalled; the run lands in CANCELLED."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"CancelAccepted\","]
#[doc = "  \"description\": \"202 for cancelRun: children are already signalled; the run lands in CANCELLED.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"cancelling\","]
#[doc = "    \"run_id\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"cancelling\": {"]
#[doc = "      \"title\": \"Cancelling\","]
#[doc = "      \"type\": \"boolean\""]
#[doc = "    },"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct CancelAccepted {
    pub cancelling: bool,
    pub run_id: i32,
}
impl CancelAccepted {
    pub fn builder() -> builder::CancelAccepted {
        Default::default()
    }
}
#[doc = "Taxonomy of observable behavior differences (master spec stage 7)."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"DivergenceClass\","]
#[doc = "  \"description\": \"Taxonomy of observable behavior differences (master spec stage 7).\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"RETURN_VALUE\","]
#[doc = "    \"EXCEPTION_TYPE\","]
#[doc = "    \"EXCEPTION_MESSAGE\","]
#[doc = "    \"EFFECT_SEQUENCE\","]
#[doc = "    \"EFFECT_ARGUMENTS\","]
#[doc = "    \"CASSETTE_MISS\","]
#[doc = "    \"CRASH\","]
#[doc = "    \"HANG\","]
#[doc = "    \"OUTPUT_STREAM\""]
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
    specta :: Type,
)]
pub enum DivergenceClass {
    #[serde(rename = "RETURN_VALUE")]
    ReturnValue,
    #[serde(rename = "EXCEPTION_TYPE")]
    ExceptionType,
    #[serde(rename = "EXCEPTION_MESSAGE")]
    ExceptionMessage,
    #[serde(rename = "EFFECT_SEQUENCE")]
    EffectSequence,
    #[serde(rename = "EFFECT_ARGUMENTS")]
    EffectArguments,
    #[serde(rename = "CASSETTE_MISS")]
    CassetteMiss,
    #[serde(rename = "CRASH")]
    Crash,
    #[serde(rename = "HANG")]
    Hang,
    #[serde(rename = "OUTPUT_STREAM")]
    OutputStream,
}
impl ::std::fmt::Display for DivergenceClass {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::ReturnValue => f.write_str("RETURN_VALUE"),
            Self::ExceptionType => f.write_str("EXCEPTION_TYPE"),
            Self::ExceptionMessage => f.write_str("EXCEPTION_MESSAGE"),
            Self::EffectSequence => f.write_str("EFFECT_SEQUENCE"),
            Self::EffectArguments => f.write_str("EFFECT_ARGUMENTS"),
            Self::CassetteMiss => f.write_str("CASSETTE_MISS"),
            Self::Crash => f.write_str("CRASH"),
            Self::Hang => f.write_str("HANG"),
            Self::OutputStream => f.write_str("OUTPUT_STREAM"),
        }
    }
}
impl ::std::str::FromStr for DivergenceClass {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "RETURN_VALUE" => Ok(Self::ReturnValue),
            "EXCEPTION_TYPE" => Ok(Self::ExceptionType),
            "EXCEPTION_MESSAGE" => Ok(Self::ExceptionMessage),
            "EFFECT_SEQUENCE" => Ok(Self::EffectSequence),
            "EFFECT_ARGUMENTS" => Ok(Self::EffectArguments),
            "CASSETTE_MISS" => Ok(Self::CassetteMiss),
            "CRASH" => Ok(Self::Crash),
            "HANG" => Ok(Self::Hang),
            "OUTPUT_STREAM" => Ok(Self::OutputStream),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for DivergenceClass {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for DivergenceClass {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for DivergenceClass {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`DivergenceDetail`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"DivergenceDetail\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"args_literal\","]
#[doc = "    \"base_summary\","]
#[doc = "    \"detail\","]
#[doc = "    \"divergence_class\","]
#[doc = "    \"head_summary\","]
#[doc = "    \"id\","]
#[doc = "    \"kwargs_literal\","]
#[doc = "    \"minimized_args\","]
#[doc = "    \"minimized_kwargs\","]
#[doc = "    \"repro_filename\","]
#[doc = "    \"run_id\","]
#[doc = "    \"severity\","]
#[doc = "    \"shrink_path\","]
#[doc = "    \"target_id\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"ai_narrative\": {"]
#[doc = "      \"title\": \"Ai Narrative\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"args_literal\": {"]
#[doc = "      \"title\": \"Args Literal\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"base_summary\": {"]
#[doc = "      \"title\": \"Base Summary\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"detail\": {"]
#[doc = "      \"title\": \"Detail\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"divergence_class\": {"]
#[doc = "      \"$ref\": \"#/$defs/DivergenceClass\""]
#[doc = "    },"]
#[doc = "    \"head_summary\": {"]
#[doc = "      \"title\": \"Head Summary\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"kwargs_literal\": {"]
#[doc = "      \"title\": \"Kwargs Literal\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"minimized_args\": {"]
#[doc = "      \"title\": \"Minimized Args\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"minimized_kwargs\": {"]
#[doc = "      \"title\": \"Minimized Kwargs\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"repro_filename\": {"]
#[doc = "      \"title\": \"Repro Filename\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"severity\": {"]
#[doc = "      \"$ref\": \"#/$defs/Severity\""]
#[doc = "    },"]
#[doc = "    \"shrink_path\": {"]
#[doc = "      \"title\": \"Shrink Path\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"type\": \"string\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"target_id\": {"]
#[doc = "      \"title\": \"Target Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct DivergenceDetail {
    #[serde(default, skip_serializing_if = "::std::option::Option::is_none")]
    pub ai_narrative: ::std::option::Option<::std::string::String>,
    pub args_literal: ::std::string::String,
    pub base_summary: ::std::string::String,
    pub detail: ::std::string::String,
    pub divergence_class: DivergenceClass,
    pub head_summary: ::std::string::String,
    pub id: i32,
    pub kwargs_literal: ::std::string::String,
    pub minimized_args: ::std::string::String,
    pub minimized_kwargs: ::std::string::String,
    pub repro_filename: ::std::string::String,
    pub run_id: i32,
    pub severity: Severity,
    pub shrink_path: ::std::vec::Vec<::std::string::String>,
    pub target_id: i32,
}
impl DivergenceDetail {
    pub fn builder() -> builder::DivergenceDetail {
        Default::default()
    }
}
#[doc = "`DivergenceSummary`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"DivergenceSummary\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"detail\","]
#[doc = "    \"divergence_class\","]
#[doc = "    \"id\","]
#[doc = "    \"minimized_args\","]
#[doc = "    \"minimized_kwargs\","]
#[doc = "    \"severity\","]
#[doc = "    \"target_id\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"detail\": {"]
#[doc = "      \"title\": \"Detail\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"divergence_class\": {"]
#[doc = "      \"$ref\": \"#/$defs/DivergenceClass\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"minimized_args\": {"]
#[doc = "      \"title\": \"Minimized Args\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"minimized_kwargs\": {"]
#[doc = "      \"title\": \"Minimized Kwargs\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"severity\": {"]
#[doc = "      \"$ref\": \"#/$defs/Severity\""]
#[doc = "    },"]
#[doc = "    \"target_id\": {"]
#[doc = "      \"title\": \"Target Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct DivergenceSummary {
    pub detail: ::std::string::String,
    pub divergence_class: DivergenceClass,
    pub id: i32,
    pub minimized_args: ::std::string::String,
    pub minimized_kwargs: ::std::string::String,
    pub severity: Severity,
    pub target_id: i32,
}
impl DivergenceSummary {
    pub fn builder() -> builder::DivergenceSummary {
        Default::default()
    }
}
#[doc = "`ErrorBody`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"ErrorBody\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"code\","]
#[doc = "    \"message\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"code\": {"]
#[doc = "      \"$ref\": \"#/$defs/ErrorCode\""]
#[doc = "    },"]
#[doc = "    \"details\": {"]
#[doc = "      \"title\": \"Details\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"object\","]
#[doc = "          \"additionalProperties\": true"]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"message\": {"]
#[doc = "      \"title\": \"Message\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct ErrorBody {
    pub code: ErrorCode,
    #[serde(default, skip_serializing_if = "::std::option::Option::is_none")]
    pub details:
        ::std::option::Option<::serde_json::Map<::std::string::String, ::serde_json::Value>>,
    pub message: ::std::string::String,
}
impl ErrorBody {
    pub fn builder() -> builder::ErrorBody {
        Default::default()
    }
}
#[doc = "Stable machine-readable codes for the `{error: {code, message, details?}}` envelope.\nRenderers switch on these; the strings are frozen."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"ErrorCode\","]
#[doc = "  \"description\": \"Stable machine-readable codes for the `{error: {code, message, details?}}` envelope.\\nRenderers switch on these; the strings are frozen.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"VALIDATION_ERROR\","]
#[doc = "    \"NOT_FOUND\","]
#[doc = "    \"IDEMPOTENCY_CONFLICT\","]
#[doc = "    \"RUN_NOT_PENDING\","]
#[doc = "    \"BUNDLE_INVALID\","]
#[doc = "    \"BUNDLE_SCHEMA_UNSUPPORTED\","]
#[doc = "    \"BUNDLE_MISMATCH\","]
#[doc = "    \"REPO_NOT_FOUND\","]
#[doc = "    \"REF_NOT_FOUND\","]
#[doc = "    \"RUN_NOT_ACTIVE\","]
#[doc = "    \"INTERNAL\""]
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
    specta :: Type,
)]
pub enum ErrorCode {
    #[serde(rename = "VALIDATION_ERROR")]
    ValidationError,
    #[serde(rename = "NOT_FOUND")]
    NotFound,
    #[serde(rename = "IDEMPOTENCY_CONFLICT")]
    IdempotencyConflict,
    #[serde(rename = "RUN_NOT_PENDING")]
    RunNotPending,
    #[serde(rename = "BUNDLE_INVALID")]
    BundleInvalid,
    #[serde(rename = "BUNDLE_SCHEMA_UNSUPPORTED")]
    BundleSchemaUnsupported,
    #[serde(rename = "BUNDLE_MISMATCH")]
    BundleMismatch,
    #[serde(rename = "REPO_NOT_FOUND")]
    RepoNotFound,
    #[serde(rename = "REF_NOT_FOUND")]
    RefNotFound,
    #[serde(rename = "RUN_NOT_ACTIVE")]
    RunNotActive,
    #[serde(rename = "INTERNAL")]
    Internal,
}
impl ::std::fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::ValidationError => f.write_str("VALIDATION_ERROR"),
            Self::NotFound => f.write_str("NOT_FOUND"),
            Self::IdempotencyConflict => f.write_str("IDEMPOTENCY_CONFLICT"),
            Self::RunNotPending => f.write_str("RUN_NOT_PENDING"),
            Self::BundleInvalid => f.write_str("BUNDLE_INVALID"),
            Self::BundleSchemaUnsupported => f.write_str("BUNDLE_SCHEMA_UNSUPPORTED"),
            Self::BundleMismatch => f.write_str("BUNDLE_MISMATCH"),
            Self::RepoNotFound => f.write_str("REPO_NOT_FOUND"),
            Self::RefNotFound => f.write_str("REF_NOT_FOUND"),
            Self::RunNotActive => f.write_str("RUN_NOT_ACTIVE"),
            Self::Internal => f.write_str("INTERNAL"),
        }
    }
}
impl ::std::str::FromStr for ErrorCode {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "VALIDATION_ERROR" => Ok(Self::ValidationError),
            "NOT_FOUND" => Ok(Self::NotFound),
            "IDEMPOTENCY_CONFLICT" => Ok(Self::IdempotencyConflict),
            "RUN_NOT_PENDING" => Ok(Self::RunNotPending),
            "BUNDLE_INVALID" => Ok(Self::BundleInvalid),
            "BUNDLE_SCHEMA_UNSUPPORTED" => Ok(Self::BundleSchemaUnsupported),
            "BUNDLE_MISMATCH" => Ok(Self::BundleMismatch),
            "REPO_NOT_FOUND" => Ok(Self::RepoNotFound),
            "REF_NOT_FOUND" => Ok(Self::RefNotFound),
            "RUN_NOT_ACTIVE" => Ok(Self::RunNotActive),
            "INTERNAL" => Ok(Self::Internal),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ErrorCode {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for ErrorCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ErrorCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`ErrorEnvelope`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"ErrorEnvelope\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"error\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"error\": {"]
#[doc = "      \"$ref\": \"#/$defs/ErrorBody\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct ErrorEnvelope {
    pub error: ErrorBody,
}
impl ErrorEnvelope {
    pub fn builder() -> builder::ErrorEnvelope {
        Default::default()
    }
}
#[doc = "`Head`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Head\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"maxLength\": 200,"]
#[doc = "  \"minLength\": 1"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct Head(::std::string::String);
impl ::std::ops::Deref for Head {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<Head> for ::std::string::String {
    fn from(value: Head) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for Head {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        if value.chars().count() > 200usize {
            return Err("longer than 200 characters".into());
        }
        if value.chars().count() < 1usize {
            return Err("shorter than 1 characters".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for Head {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Head {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Head {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for Head {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`HeadSha`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Head Sha\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"pattern\": \"^[0-9a-f]{40}$\""]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct HeadSha(::std::string::String);
impl ::std::ops::Deref for HeadSha {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<HeadSha> for ::std::string::String {
    fn from(value: HeadSha) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for HeadSha {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        static PATTERN: ::std::sync::LazyLock<::regress::Regex> =
            ::std::sync::LazyLock::new(|| ::regress::Regex::new("^[0-9a-f]{40}$").unwrap());
        if PATTERN.find(value).is_none() {
            return Err("doesn't match pattern \"^[0-9a-f]{40}$\"".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for HeadSha {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for HeadSha {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for HeadSha {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for HeadSha {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`HealthResponse`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"HealthResponse\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"engine_version\","]
#[doc = "    \"schema_version\","]
#[doc = "    \"status\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"engine_version\": {"]
#[doc = "      \"title\": \"Engine Version\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"schema_version\": {"]
#[doc = "      \"title\": \"Schema Version\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"status\": {"]
#[doc = "      \"title\": \"Status\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"const\": \"ok\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct HealthResponse {
    pub engine_version: ::std::string::String,
    pub schema_version: i32,
    pub status: ::std::string::String,
}
impl HealthResponse {
    pub fn builder() -> builder::HealthResponse {
        Default::default()
    }
}
#[doc = "`Lang`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Lang\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"PYTHON\","]
#[doc = "    \"TYPESCRIPT\""]
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
    specta :: Type,
)]
pub enum Lang {
    #[serde(rename = "PYTHON")]
    Python,
    #[serde(rename = "TYPESCRIPT")]
    Typescript,
}
impl ::std::fmt::Display for Lang {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Python => f.write_str("PYTHON"),
            Self::Typescript => f.write_str("TYPESCRIPT"),
        }
    }
}
impl ::std::str::FromStr for Lang {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "PYTHON" => Ok(Self::Python),
            "TYPESCRIPT" => Ok(Self::Typescript),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Lang {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Lang {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Lang {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`LocalProveRequest`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"LocalProveRequest\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"base\","]
#[doc = "    \"head\","]
#[doc = "    \"repo_path\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"base\": {"]
#[doc = "      \"title\": \"Base\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"maxLength\": 200,"]
#[doc = "      \"minLength\": 1"]
#[doc = "    },"]
#[doc = "    \"head\": {"]
#[doc = "      \"title\": \"Head\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"maxLength\": 200,"]
#[doc = "      \"minLength\": 1"]
#[doc = "    },"]
#[doc = "    \"max_inputs\": {"]
#[doc = "      \"title\": \"Max Inputs\","]
#[doc = "      \"default\": 300,"]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"repo_path\": {"]
#[doc = "      \"title\": \"Repo Path\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"minLength\": 1"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct LocalProveRequest {
    pub base: Base,
    pub head: Head,
    #[serde(default = "defaults::default_u64::<i32, 300>")]
    pub max_inputs: i32,
    pub repo_path: RepoPath,
}
impl LocalProveRequest {
    pub fn builder() -> builder::LocalProveRequest {
        Default::default()
    }
}
#[doc = "`LogRecordOut`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"LogRecordOut\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"component\","]
#[doc = "    \"level\","]
#[doc = "    \"message\","]
#[doc = "    \"ts\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"component\": {"]
#[doc = "      \"title\": \"Component\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"level\": {"]
#[doc = "      \"title\": \"Level\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"message\": {"]
#[doc = "      \"title\": \"Message\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"ts\": {"]
#[doc = "      \"title\": \"Ts\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct LogRecordOut {
    pub component: ::std::string::String,
    pub level: ::std::string::String,
    pub message: ::std::string::String,
    pub ts: ::std::string::String,
}
impl LogRecordOut {
    pub fn builder() -> builder::LogRecordOut {
        Default::default()
    }
}
#[doc = "`PageRunSummary`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Page[RunSummary]\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"items\","]
#[doc = "    \"next_cursor\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"items\": {"]
#[doc = "      \"title\": \"Items\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"$ref\": \"#/$defs/RunSummary\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"next_cursor\": {"]
#[doc = "      \"title\": \"Next Cursor\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct PageRunSummary {
    pub items: ::std::vec::Vec<RunSummary>,
    pub next_cursor: ::std::option::Option<::std::string::String>,
}
impl PageRunSummary {
    pub fn builder() -> builder::PageRunSummary {
        Default::default()
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
    specta :: Type,
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
#[doc = "`Repo`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Repo\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"maxLength\": 200,"]
#[doc = "  \"minLength\": 1"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct Repo(::std::string::String);
impl ::std::ops::Deref for Repo {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<Repo> for ::std::string::String {
    fn from(value: Repo) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for Repo {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        if value.chars().count() > 200usize {
            return Err("longer than 200 characters".into());
        }
        if value.chars().count() < 1usize {
            return Err("shorter than 1 characters".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for Repo {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Repo {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Repo {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for Repo {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`RepoPath`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Repo Path\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"minLength\": 1"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct RepoPath(::std::string::String);
impl ::std::ops::Deref for RepoPath {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<RepoPath> for ::std::string::String {
    fn from(value: RepoPath) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for RepoPath {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        if value.chars().count() < 1usize {
            return Err("shorter than 1 characters".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for RepoPath {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for RepoPath {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for RepoPath {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for RepoPath {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "`RunCreate`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunCreate\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"base_sha\","]
#[doc = "    \"head_sha\","]
#[doc = "    \"repo\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"base_sha\": {"]
#[doc = "      \"title\": \"Base Sha\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"pattern\": \"^[0-9a-f]{40}$\""]
#[doc = "    },"]
#[doc = "    \"head_sha\": {"]
#[doc = "      \"title\": \"Head Sha\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"pattern\": \"^[0-9a-f]{40}$\""]
#[doc = "    },"]
#[doc = "    \"repo\": {"]
#[doc = "      \"title\": \"Repo\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"maxLength\": 200,"]
#[doc = "      \"minLength\": 1"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct RunCreate {
    pub base_sha: BaseSha,
    pub head_sha: HeadSha,
    pub repo: Repo,
}
impl RunCreate {
    pub fn builder() -> builder::RunCreate {
        Default::default()
    }
}
#[doc = "`RunCreated`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunCreated\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"run_id\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct RunCreated {
    pub run_id: i32,
}
impl RunCreated {
    pub fn builder() -> builder::RunCreated {
        Default::default()
    }
}
#[doc = "`RunDetail`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunDetail\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"base_deps\","]
#[doc = "    \"base_sha\","]
#[doc = "    \"budget_max_inputs\","]
#[doc = "    \"bundle_created_at\","]
#[doc = "    \"created_at\","]
#[doc = "    \"divergence_count\","]
#[doc = "    \"engine_version\","]
#[doc = "    \"head_deps\","]
#[doc = "    \"head_sha\","]
#[doc = "    \"id\","]
#[doc = "    \"repo\","]
#[doc = "    \"sandbox_assurance\","]
#[doc = "    \"sandbox_tier\","]
#[doc = "    \"schema_version\","]
#[doc = "    \"status\","]
#[doc = "    \"target_count\","]
#[doc = "    \"targets\","]
#[doc = "    \"verdict\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"base_deps\": {"]
#[doc = "      \"title\": \"Base Deps\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"base_sha\": {"]
#[doc = "      \"title\": \"Base Sha\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"budget_max_inputs\": {"]
#[doc = "      \"title\": \"Budget Max Inputs\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"integer\","]
#[doc = "          \"maximum\": 2147483647.0,"]
#[doc = "          \"minimum\": -2147483648.0"]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"bundle_created_at\": {"]
#[doc = "      \"title\": \"Bundle Created At\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"created_at\": {"]
#[doc = "      \"title\": \"Created At\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"format\": \"date-time\""]
#[doc = "    },"]
#[doc = "    \"divergence_count\": {"]
#[doc = "      \"title\": \"Divergence Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"engine_version\": {"]
#[doc = "      \"title\": \"Engine Version\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"head_deps\": {"]
#[doc = "      \"title\": \"Head Deps\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"head_sha\": {"]
#[doc = "      \"title\": \"Head Sha\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"repo\": {"]
#[doc = "      \"title\": \"Repo\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"sandbox_assurance\": {"]
#[doc = "      \"title\": \"Sandbox Assurance\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"sandbox_tier\": {"]
#[doc = "      \"title\": \"Sandbox Tier\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"schema_version\": {"]
#[doc = "      \"title\": \"Schema Version\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"integer\","]
#[doc = "          \"maximum\": 2147483647.0,"]
#[doc = "          \"minimum\": -2147483648.0"]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"status\": {"]
#[doc = "      \"$ref\": \"#/$defs/RunStatus\""]
#[doc = "    },"]
#[doc = "    \"target_count\": {"]
#[doc = "      \"title\": \"Target Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"targets\": {"]
#[doc = "      \"title\": \"Targets\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"$ref\": \"#/$defs/TargetSummary\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"verdict\": {"]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"$ref\": \"#/$defs/Verdict\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct RunDetail {
    pub base_deps: ::std::option::Option<::std::string::String>,
    pub base_sha: ::std::string::String,
    pub budget_max_inputs: ::std::option::Option<i32>,
    pub bundle_created_at: ::std::option::Option<::std::string::String>,
    pub created_at: ::chrono::DateTime<::chrono::offset::Utc>,
    pub divergence_count: i32,
    pub engine_version: ::std::option::Option<::std::string::String>,
    pub head_deps: ::std::option::Option<::std::string::String>,
    pub head_sha: ::std::string::String,
    pub id: i32,
    pub repo: ::std::string::String,
    pub sandbox_assurance: ::std::option::Option<::std::string::String>,
    pub sandbox_tier: ::std::option::Option<::std::string::String>,
    pub schema_version: ::std::option::Option<i32>,
    pub status: RunStatus,
    pub target_count: i32,
    pub targets: ::std::vec::Vec<TargetSummary>,
    pub verdict: ::std::option::Option<Verdict>,
}
impl RunDetail {
    pub fn builder() -> builder::RunDetail {
        Default::default()
    }
}
#[doc = "`RunEventOut`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunEventOut\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"level\","]
#[doc = "    \"message\","]
#[doc = "    \"stage\","]
#[doc = "    \"ts\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"level\": {"]
#[doc = "      \"title\": \"Level\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"message\": {"]
#[doc = "      \"title\": \"Message\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"stage\": {"]
#[doc = "      \"title\": \"Stage\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"ts\": {"]
#[doc = "      \"title\": \"Ts\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"format\": \"date-time\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct RunEventOut {
    pub level: ::std::string::String,
    pub message: ::std::string::String,
    pub stage: ::std::string::String,
    pub ts: ::chrono::DateTime<::chrono::offset::Utc>,
}
impl RunEventOut {
    pub fn builder() -> builder::RunEventOut {
        Default::default()
    }
}
#[doc = "Run lifecycle. PENDING (created) → COMPLETE (bundle ingested), or CANCELLED (the user\nstopped the prove — honest terminal state, no verdict ever claimed, L2/L11); further\norchestration states are added — deliberately breaking the generated TS — when arq lands."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunStatus\","]
#[doc = "  \"description\": \"Run lifecycle. PENDING (created) → COMPLETE (bundle ingested), or CANCELLED (the user\\nstopped the prove — honest terminal state, no verdict ever claimed, L2/L11); further\\norchestration states are added — deliberately breaking the generated TS — when arq lands.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"PENDING\","]
#[doc = "    \"COMPLETE\","]
#[doc = "    \"CANCELLED\""]
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
    specta :: Type,
)]
pub enum RunStatus {
    #[serde(rename = "PENDING")]
    Pending,
    #[serde(rename = "COMPLETE")]
    Complete,
    #[serde(rename = "CANCELLED")]
    Cancelled,
}
impl ::std::fmt::Display for RunStatus {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Pending => f.write_str("PENDING"),
            Self::Complete => f.write_str("COMPLETE"),
            Self::Cancelled => f.write_str("CANCELLED"),
        }
    }
}
impl ::std::str::FromStr for RunStatus {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "PENDING" => Ok(Self::Pending),
            "COMPLETE" => Ok(Self::Complete),
            "CANCELLED" => Ok(Self::Cancelled),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for RunStatus {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for RunStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for RunStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`RunSummary`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"RunSummary\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"base_sha\","]
#[doc = "    \"created_at\","]
#[doc = "    \"divergence_count\","]
#[doc = "    \"head_sha\","]
#[doc = "    \"id\","]
#[doc = "    \"repo\","]
#[doc = "    \"status\","]
#[doc = "    \"target_count\","]
#[doc = "    \"verdict\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"base_sha\": {"]
#[doc = "      \"title\": \"Base Sha\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"created_at\": {"]
#[doc = "      \"title\": \"Created At\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"format\": \"date-time\""]
#[doc = "    },"]
#[doc = "    \"divergence_count\": {"]
#[doc = "      \"title\": \"Divergence Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"head_sha\": {"]
#[doc = "      \"title\": \"Head Sha\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"repo\": {"]
#[doc = "      \"title\": \"Repo\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"status\": {"]
#[doc = "      \"$ref\": \"#/$defs/RunStatus\""]
#[doc = "    },"]
#[doc = "    \"target_count\": {"]
#[doc = "      \"title\": \"Target Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"verdict\": {"]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"$ref\": \"#/$defs/Verdict\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct RunSummary {
    pub base_sha: ::std::string::String,
    pub created_at: ::chrono::DateTime<::chrono::offset::Utc>,
    pub divergence_count: i32,
    pub head_sha: ::std::string::String,
    pub id: i32,
    pub repo: ::std::string::String,
    pub status: RunStatus,
    pub target_count: i32,
    pub verdict: ::std::option::Option<Verdict>,
}
impl RunSummary {
    pub fn builder() -> builder::RunSummary {
        Default::default()
    }
}
#[doc = "`SearchHit`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"SearchHit\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"divergence_class\","]
#[doc = "    \"divergence_id\","]
#[doc = "    \"module\","]
#[doc = "    \"qualname\","]
#[doc = "    \"run_id\","]
#[doc = "    \"severity\","]
#[doc = "    \"snippet\","]
#[doc = "    \"target_id\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"divergence_class\": {"]
#[doc = "      \"$ref\": \"#/$defs/DivergenceClass\""]
#[doc = "    },"]
#[doc = "    \"divergence_id\": {"]
#[doc = "      \"title\": \"Divergence Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"module\": {"]
#[doc = "      \"title\": \"Module\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"qualname\": {"]
#[doc = "      \"title\": \"Qualname\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"severity\": {"]
#[doc = "      \"$ref\": \"#/$defs/Severity\""]
#[doc = "    },"]
#[doc = "    \"snippet\": {"]
#[doc = "      \"title\": \"Snippet\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"target_id\": {"]
#[doc = "      \"title\": \"Target Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct SearchHit {
    pub divergence_class: DivergenceClass,
    pub divergence_id: i32,
    pub module: ::std::string::String,
    pub qualname: ::std::string::String,
    pub run_id: i32,
    pub severity: Severity,
    pub snippet: ::std::string::String,
    pub target_id: i32,
}
impl SearchHit {
    pub fn builder() -> builder::SearchHit {
        Default::default()
    }
}
#[doc = "`SearchResults`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"SearchResults\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"hits\","]
#[doc = "    \"query\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"hits\": {"]
#[doc = "      \"title\": \"Hits\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"$ref\": \"#/$defs/SearchHit\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"query\": {"]
#[doc = "      \"title\": \"Query\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct SearchResults {
    pub hits: ::std::vec::Vec<SearchHit>,
    pub query: ::std::string::String,
}
impl SearchResults {
    pub fn builder() -> builder::SearchResults {
        Default::default()
    }
}
#[doc = "`ServerUrl`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Server Url\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"maxLength\": 2000,"]
#[doc = "  \"minLength\": 1"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(
    :: serde :: Serialize, Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, specta :: Type,
)]
#[serde(transparent)]
pub struct ServerUrl(::std::string::String);
impl ::std::ops::Deref for ServerUrl {
    type Target = ::std::string::String;
    fn deref(&self) -> &::std::string::String {
        &self.0
    }
}
impl ::std::convert::From<ServerUrl> for ::std::string::String {
    fn from(value: ServerUrl) -> Self {
        value.0
    }
}
impl ::std::str::FromStr for ServerUrl {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        if value.chars().count() > 2000usize {
            return Err("longer than 2000 characters".into());
        }
        if value.chars().count() < 1usize {
            return Err("shorter than 1 characters".into());
        }
        Ok(Self(value.to_string()))
    }
}
impl ::std::convert::TryFrom<&str> for ServerUrl {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for ServerUrl {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ServerUrl {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl<'de> ::serde::Deserialize<'de> for ServerUrl {
    fn deserialize<D>(deserializer: D) -> ::std::result::Result<Self, D::Error>
    where
        D: ::serde::Deserializer<'de>,
    {
        ::std::string::String::deserialize(deserializer)?
            .parse()
            .map_err(|e: self::error::ConversionError| {
                <D::Error as ::serde::de::Error>::custom(e.to_string())
            })
    }
}
#[doc = "Reporting severity: -0.0 vs 0.0 is LOW; a head-only crash is HEADLINE."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Severity\","]
#[doc = "  \"description\": \"Reporting severity: -0.0 vs 0.0 is LOW; a head-only crash is HEADLINE.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"LOW\","]
#[doc = "    \"NORMAL\","]
#[doc = "    \"HEADLINE\""]
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
    specta :: Type,
)]
pub enum Severity {
    #[serde(rename = "LOW")]
    Low,
    #[serde(rename = "NORMAL")]
    Normal,
    #[serde(rename = "HEADLINE")]
    Headline,
}
impl ::std::fmt::Display for Severity {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Low => f.write_str("LOW"),
            Self::Normal => f.write_str("NORMAL"),
            Self::Headline => f.write_str("HEADLINE"),
        }
    }
}
impl ::std::str::FromStr for Severity {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "LOW" => Ok(Self::Low),
            "NORMAL" => Ok(Self::Normal),
            "HEADLINE" => Ok(Self::Headline),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Severity {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Severity {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Severity {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`SyncPushRequest`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"SyncPushRequest\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"server_url\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"server_url\": {"]
#[doc = "      \"title\": \"Server Url\","]
#[doc = "      \"type\": \"string\","]
#[doc = "      \"maxLength\": 2000,"]
#[doc = "      \"minLength\": 1"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct SyncPushRequest {
    pub server_url: ServerUrl,
}
impl SyncPushRequest {
    pub fn builder() -> builder::SyncPushRequest {
        Default::default()
    }
}
#[doc = "`SyncReport`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"SyncReport\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"candidates\","]
#[doc = "    \"errors\","]
#[doc = "    \"failed\","]
#[doc = "    \"pushed\","]
#[doc = "    \"remaining\","]
#[doc = "    \"skipped\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"candidates\": {"]
#[doc = "      \"title\": \"Candidates\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"errors\": {"]
#[doc = "      \"title\": \"Errors\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"type\": \"string\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"failed\": {"]
#[doc = "      \"title\": \"Failed\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"pushed\": {"]
#[doc = "      \"title\": \"Pushed\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"remaining\": {"]
#[doc = "      \"title\": \"Remaining\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"skipped\": {"]
#[doc = "      \"title\": \"Skipped\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct SyncReport {
    pub candidates: i32,
    pub errors: ::std::vec::Vec<::std::string::String>,
    pub failed: i32,
    pub pushed: i32,
    pub remaining: i32,
    pub skipped: i32,
}
impl SyncReport {
    pub fn builder() -> builder::SyncReport {
        Default::default()
    }
}
#[doc = "Stage-1 classification of a changed symbol."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"TargetClassification\","]
#[doc = "  \"description\": \"Stage-1 classification of a changed symbol.\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"PURE_CANDIDATE\","]
#[doc = "    \"IMPURE_RECORDABLE\","]
#[doc = "    \"UNREACHABLE\","]
#[doc = "    \"SYNTHESIZED\","]
#[doc = "    \"TYPE_SYNTHESIZED\""]
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
    specta :: Type,
)]
pub enum TargetClassification {
    #[serde(rename = "PURE_CANDIDATE")]
    PureCandidate,
    #[serde(rename = "IMPURE_RECORDABLE")]
    ImpureRecordable,
    #[serde(rename = "UNREACHABLE")]
    Unreachable,
    #[serde(rename = "SYNTHESIZED")]
    Synthesized,
    #[serde(rename = "TYPE_SYNTHESIZED")]
    TypeSynthesized,
}
impl ::std::fmt::Display for TargetClassification {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::PureCandidate => f.write_str("PURE_CANDIDATE"),
            Self::ImpureRecordable => f.write_str("IMPURE_RECORDABLE"),
            Self::Unreachable => f.write_str("UNREACHABLE"),
            Self::Synthesized => f.write_str("SYNTHESIZED"),
            Self::TypeSynthesized => f.write_str("TYPE_SYNTHESIZED"),
        }
    }
}
impl ::std::str::FromStr for TargetClassification {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "PURE_CANDIDATE" => Ok(Self::PureCandidate),
            "IMPURE_RECORDABLE" => Ok(Self::ImpureRecordable),
            "UNREACHABLE" => Ok(Self::Unreachable),
            "SYNTHESIZED" => Ok(Self::Synthesized),
            "TYPE_SYNTHESIZED" => Ok(Self::TypeSynthesized),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for TargetClassification {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for TargetClassification {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for TargetClassification {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = "`TargetDetail`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"TargetDetail\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"changed_line_coverage\","]
#[doc = "    \"classification\","]
#[doc = "    \"divergence_count\","]
#[doc = "    \"divergences\","]
#[doc = "    \"equivalent_inputs\","]
#[doc = "    \"file_path\","]
#[doc = "    \"id\","]
#[doc = "    \"inputs_run\","]
#[doc = "    \"lang\","]
#[doc = "    \"module\","]
#[doc = "    \"qualname\","]
#[doc = "    \"reason_code\","]
#[doc = "    \"reason_detail\","]
#[doc = "    \"run_id\","]
#[doc = "    \"unprovable_inputs\","]
#[doc = "    \"verdict\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"changed_line_coverage\": {"]
#[doc = "      \"title\": \"Changed Line Coverage\","]
#[doc = "      \"type\": \"number\""]
#[doc = "    },"]
#[doc = "    \"classification\": {"]
#[doc = "      \"$ref\": \"#/$defs/TargetClassification\""]
#[doc = "    },"]
#[doc = "    \"divergence_count\": {"]
#[doc = "      \"title\": \"Divergence Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"divergences\": {"]
#[doc = "      \"title\": \"Divergences\","]
#[doc = "      \"type\": \"array\","]
#[doc = "      \"items\": {"]
#[doc = "        \"$ref\": \"#/$defs/DivergenceSummary\""]
#[doc = "      }"]
#[doc = "    },"]
#[doc = "    \"equivalent_inputs\": {"]
#[doc = "      \"title\": \"Equivalent Inputs\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"file_path\": {"]
#[doc = "      \"title\": \"File Path\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"inputs_run\": {"]
#[doc = "      \"title\": \"Inputs Run\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"lang\": {"]
#[doc = "      \"$ref\": \"#/$defs/Lang\""]
#[doc = "    },"]
#[doc = "    \"module\": {"]
#[doc = "      \"title\": \"Module\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"qualname\": {"]
#[doc = "      \"title\": \"Qualname\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"reason_code\": {"]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"$ref\": \"#/$defs/ReasonCode\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"reason_detail\": {"]
#[doc = "      \"title\": \"Reason Detail\","]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"type\": \"string\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"unprovable_inputs\": {"]
#[doc = "      \"title\": \"Unprovable Inputs\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"verdict\": {"]
#[doc = "      \"$ref\": \"#/$defs/Verdict\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct TargetDetail {
    pub changed_line_coverage: f64,
    pub classification: TargetClassification,
    pub divergence_count: i32,
    pub divergences: ::std::vec::Vec<DivergenceSummary>,
    pub equivalent_inputs: i32,
    pub file_path: ::std::string::String,
    pub id: i32,
    pub inputs_run: i32,
    pub lang: Lang,
    pub module: ::std::string::String,
    pub qualname: ::std::string::String,
    pub reason_code: ::std::option::Option<ReasonCode>,
    pub reason_detail: ::std::option::Option<::std::string::String>,
    pub run_id: i32,
    pub unprovable_inputs: i32,
    pub verdict: Verdict,
}
impl TargetDetail {
    pub fn builder() -> builder::TargetDetail {
        Default::default()
    }
}
#[doc = "`TargetSummary`"]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"TargetSummary\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"required\": ["]
#[doc = "    \"changed_line_coverage\","]
#[doc = "    \"classification\","]
#[doc = "    \"divergence_count\","]
#[doc = "    \"file_path\","]
#[doc = "    \"id\","]
#[doc = "    \"lang\","]
#[doc = "    \"module\","]
#[doc = "    \"qualname\","]
#[doc = "    \"reason_code\","]
#[doc = "    \"run_id\","]
#[doc = "    \"verdict\""]
#[doc = "  ],"]
#[doc = "  \"properties\": {"]
#[doc = "    \"changed_line_coverage\": {"]
#[doc = "      \"title\": \"Changed Line Coverage\","]
#[doc = "      \"type\": \"number\""]
#[doc = "    },"]
#[doc = "    \"classification\": {"]
#[doc = "      \"$ref\": \"#/$defs/TargetClassification\""]
#[doc = "    },"]
#[doc = "    \"divergence_count\": {"]
#[doc = "      \"title\": \"Divergence Count\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"file_path\": {"]
#[doc = "      \"title\": \"File Path\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"id\": {"]
#[doc = "      \"title\": \"Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"lang\": {"]
#[doc = "      \"$ref\": \"#/$defs/Lang\""]
#[doc = "    },"]
#[doc = "    \"module\": {"]
#[doc = "      \"title\": \"Module\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"qualname\": {"]
#[doc = "      \"title\": \"Qualname\","]
#[doc = "      \"type\": \"string\""]
#[doc = "    },"]
#[doc = "    \"reason_code\": {"]
#[doc = "      \"anyOf\": ["]
#[doc = "        {"]
#[doc = "          \"$ref\": \"#/$defs/ReasonCode\""]
#[doc = "        },"]
#[doc = "        {"]
#[doc = "          \"type\": \"null\""]
#[doc = "        }"]
#[doc = "      ]"]
#[doc = "    },"]
#[doc = "    \"run_id\": {"]
#[doc = "      \"title\": \"Run Id\","]
#[doc = "      \"type\": \"integer\","]
#[doc = "      \"maximum\": 2147483647.0,"]
#[doc = "      \"minimum\": -2147483648.0"]
#[doc = "    },"]
#[doc = "    \"verdict\": {"]
#[doc = "      \"$ref\": \"#/$defs/Verdict\""]
#[doc = "    }"]
#[doc = "  }"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
pub struct TargetSummary {
    pub changed_line_coverage: f64,
    pub classification: TargetClassification,
    pub divergence_count: i32,
    pub file_path: ::std::string::String,
    pub id: i32,
    pub lang: Lang,
    pub module: ::std::string::String,
    pub qualname: ::std::string::String,
    pub reason_code: ::std::option::Option<ReasonCode>,
    pub run_id: i32,
    pub verdict: Verdict,
}
impl TargetSummary {
    pub fn builder() -> builder::TargetSummary {
        Default::default()
    }
}
#[doc = "Generated from openapi.json — do not edit; run `make gen-contracts`."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"TempestDomain\","]
#[doc = "  \"description\": \"Generated from openapi.json — do not edit; run `make gen-contracts`.\","]
#[doc = "  \"type\": \"object\","]
#[doc = "  \"additionalProperties\": false"]
#[doc = "}"]
#[doc = r" ```"]
#[doc = r" </details>"]
#[derive(:: serde :: Deserialize, :: serde :: Serialize, Clone, Debug, specta :: Type)]
#[serde(deny_unknown_fields)]
pub struct TempestDomain {}
impl ::std::default::Default for TempestDomain {
    fn default() -> Self {
        Self {}
    }
}
impl TempestDomain {
    pub fn builder() -> builder::TempestDomain {
        Default::default()
    }
}
#[doc = "The only verdicts Tempest can emit (Law L2)."]
#[doc = r""]
#[doc = r" <details><summary>JSON schema</summary>"]
#[doc = r""]
#[doc = r" ```json"]
#[doc = "{"]
#[doc = "  \"title\": \"Verdict\","]
#[doc = "  \"description\": \"The only verdicts Tempest can emit (Law L2).\","]
#[doc = "  \"type\": \"string\","]
#[doc = "  \"enum\": ["]
#[doc = "    \"DIVERGENT\","]
#[doc = "    \"EQUIVALENT_UNDER_BUDGET\","]
#[doc = "    \"UNPROVEN\","]
#[doc = "    \"ERROR\""]
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
    specta :: Type,
)]
pub enum Verdict {
    #[serde(rename = "DIVERGENT")]
    Divergent,
    #[serde(rename = "EQUIVALENT_UNDER_BUDGET")]
    EquivalentUnderBudget,
    #[serde(rename = "UNPROVEN")]
    Unproven,
    #[serde(rename = "ERROR")]
    Error,
}
impl ::std::fmt::Display for Verdict {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Divergent => f.write_str("DIVERGENT"),
            Self::EquivalentUnderBudget => f.write_str("EQUIVALENT_UNDER_BUDGET"),
            Self::Unproven => f.write_str("UNPROVEN"),
            Self::Error => f.write_str("ERROR"),
        }
    }
}
impl ::std::str::FromStr for Verdict {
    type Err = self::error::ConversionError;
    fn from_str(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "DIVERGENT" => Ok(Self::Divergent),
            "EQUIVALENT_UNDER_BUDGET" => Ok(Self::EquivalentUnderBudget),
            "UNPROVEN" => Ok(Self::Unproven),
            "ERROR" => Ok(Self::Error),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Verdict {
    type Error = self::error::ConversionError;
    fn try_from(value: &str) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<&::std::string::String> for Verdict {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Verdict {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
#[doc = r" Types for composing complex structures."]
pub mod builder {
    #[derive(Clone, Debug)]
    pub struct BodyImportRunBundle {
        file: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for BodyImportRunBundle {
        fn default() -> Self {
            Self {
                file: Err("no value supplied for file".to_string()),
            }
        }
    }
    impl BodyImportRunBundle {
        pub fn file<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.file = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for file: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<BodyImportRunBundle> for super::BodyImportRunBundle {
        type Error = super::error::ConversionError;
        fn try_from(
            value: BodyImportRunBundle,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self { file: value.file? })
        }
    }
    impl ::std::convert::From<super::BodyImportRunBundle> for BodyImportRunBundle {
        fn from(value: super::BodyImportRunBundle) -> Self {
            Self {
                file: Ok(value.file),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct BundlePresenceRequest {
        digests:
            ::std::result::Result<::std::vec::Vec<::std::string::String>, ::std::string::String>,
    }
    impl ::std::default::Default for BundlePresenceRequest {
        fn default() -> Self {
            Self {
                digests: Err("no value supplied for digests".to_string()),
            }
        }
    }
    impl BundlePresenceRequest {
        pub fn digests<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.digests = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for digests: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<BundlePresenceRequest> for super::BundlePresenceRequest {
        type Error = super::error::ConversionError;
        fn try_from(
            value: BundlePresenceRequest,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                digests: value.digests?,
            })
        }
    }
    impl ::std::convert::From<super::BundlePresenceRequest> for BundlePresenceRequest {
        fn from(value: super::BundlePresenceRequest) -> Self {
            Self {
                digests: Ok(value.digests),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct BundlePresenceResponse {
        missing:
            ::std::result::Result<::std::vec::Vec<::std::string::String>, ::std::string::String>,
        present:
            ::std::result::Result<::std::vec::Vec<::std::string::String>, ::std::string::String>,
    }
    impl ::std::default::Default for BundlePresenceResponse {
        fn default() -> Self {
            Self {
                missing: Err("no value supplied for missing".to_string()),
                present: Err("no value supplied for present".to_string()),
            }
        }
    }
    impl BundlePresenceResponse {
        pub fn missing<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.missing = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for missing: {e}"));
            self
        }
        pub fn present<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.present = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for present: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<BundlePresenceResponse> for super::BundlePresenceResponse {
        type Error = super::error::ConversionError;
        fn try_from(
            value: BundlePresenceResponse,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                missing: value.missing?,
                present: value.present?,
            })
        }
    }
    impl ::std::convert::From<super::BundlePresenceResponse> for BundlePresenceResponse {
        fn from(value: super::BundlePresenceResponse) -> Self {
            Self {
                missing: Ok(value.missing),
                present: Ok(value.present),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct CancelAccepted {
        cancelling: ::std::result::Result<bool, ::std::string::String>,
        run_id: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for CancelAccepted {
        fn default() -> Self {
            Self {
                cancelling: Err("no value supplied for cancelling".to_string()),
                run_id: Err("no value supplied for run_id".to_string()),
            }
        }
    }
    impl CancelAccepted {
        pub fn cancelling<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<bool>,
            T::Error: ::std::fmt::Display,
        {
            self.cancelling = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for cancelling: {e}"));
            self
        }
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<CancelAccepted> for super::CancelAccepted {
        type Error = super::error::ConversionError;
        fn try_from(
            value: CancelAccepted,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                cancelling: value.cancelling?,
                run_id: value.run_id?,
            })
        }
    }
    impl ::std::convert::From<super::CancelAccepted> for CancelAccepted {
        fn from(value: super::CancelAccepted) -> Self {
            Self {
                cancelling: Ok(value.cancelling),
                run_id: Ok(value.run_id),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct DivergenceDetail {
        ai_narrative: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        args_literal: ::std::result::Result<::std::string::String, ::std::string::String>,
        base_summary: ::std::result::Result<::std::string::String, ::std::string::String>,
        detail: ::std::result::Result<::std::string::String, ::std::string::String>,
        divergence_class: ::std::result::Result<super::DivergenceClass, ::std::string::String>,
        head_summary: ::std::result::Result<::std::string::String, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        kwargs_literal: ::std::result::Result<::std::string::String, ::std::string::String>,
        minimized_args: ::std::result::Result<::std::string::String, ::std::string::String>,
        minimized_kwargs: ::std::result::Result<::std::string::String, ::std::string::String>,
        repro_filename: ::std::result::Result<::std::string::String, ::std::string::String>,
        run_id: ::std::result::Result<i32, ::std::string::String>,
        severity: ::std::result::Result<super::Severity, ::std::string::String>,
        shrink_path:
            ::std::result::Result<::std::vec::Vec<::std::string::String>, ::std::string::String>,
        target_id: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for DivergenceDetail {
        fn default() -> Self {
            Self {
                ai_narrative: Ok(Default::default()),
                args_literal: Err("no value supplied for args_literal".to_string()),
                base_summary: Err("no value supplied for base_summary".to_string()),
                detail: Err("no value supplied for detail".to_string()),
                divergence_class: Err("no value supplied for divergence_class".to_string()),
                head_summary: Err("no value supplied for head_summary".to_string()),
                id: Err("no value supplied for id".to_string()),
                kwargs_literal: Err("no value supplied for kwargs_literal".to_string()),
                minimized_args: Err("no value supplied for minimized_args".to_string()),
                minimized_kwargs: Err("no value supplied for minimized_kwargs".to_string()),
                repro_filename: Err("no value supplied for repro_filename".to_string()),
                run_id: Err("no value supplied for run_id".to_string()),
                severity: Err("no value supplied for severity".to_string()),
                shrink_path: Err("no value supplied for shrink_path".to_string()),
                target_id: Err("no value supplied for target_id".to_string()),
            }
        }
    }
    impl DivergenceDetail {
        pub fn ai_narrative<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.ai_narrative = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for ai_narrative: {e}"));
            self
        }
        pub fn args_literal<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.args_literal = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for args_literal: {e}"));
            self
        }
        pub fn base_summary<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.base_summary = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base_summary: {e}"));
            self
        }
        pub fn detail<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.detail = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for detail: {e}"));
            self
        }
        pub fn divergence_class<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::DivergenceClass>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_class = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_class: {e}"));
            self
        }
        pub fn head_summary<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.head_summary = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head_summary: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn kwargs_literal<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.kwargs_literal = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for kwargs_literal: {e}"));
            self
        }
        pub fn minimized_args<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.minimized_args = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for minimized_args: {e}"));
            self
        }
        pub fn minimized_kwargs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.minimized_kwargs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for minimized_kwargs: {e}"));
            self
        }
        pub fn repro_filename<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.repro_filename = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for repro_filename: {e}"));
            self
        }
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
        pub fn severity<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Severity>,
            T::Error: ::std::fmt::Display,
        {
            self.severity = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for severity: {e}"));
            self
        }
        pub fn shrink_path<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.shrink_path = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for shrink_path: {e}"));
            self
        }
        pub fn target_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.target_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for target_id: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<DivergenceDetail> for super::DivergenceDetail {
        type Error = super::error::ConversionError;
        fn try_from(
            value: DivergenceDetail,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                ai_narrative: value.ai_narrative?,
                args_literal: value.args_literal?,
                base_summary: value.base_summary?,
                detail: value.detail?,
                divergence_class: value.divergence_class?,
                head_summary: value.head_summary?,
                id: value.id?,
                kwargs_literal: value.kwargs_literal?,
                minimized_args: value.minimized_args?,
                minimized_kwargs: value.minimized_kwargs?,
                repro_filename: value.repro_filename?,
                run_id: value.run_id?,
                severity: value.severity?,
                shrink_path: value.shrink_path?,
                target_id: value.target_id?,
            })
        }
    }
    impl ::std::convert::From<super::DivergenceDetail> for DivergenceDetail {
        fn from(value: super::DivergenceDetail) -> Self {
            Self {
                ai_narrative: Ok(value.ai_narrative),
                args_literal: Ok(value.args_literal),
                base_summary: Ok(value.base_summary),
                detail: Ok(value.detail),
                divergence_class: Ok(value.divergence_class),
                head_summary: Ok(value.head_summary),
                id: Ok(value.id),
                kwargs_literal: Ok(value.kwargs_literal),
                minimized_args: Ok(value.minimized_args),
                minimized_kwargs: Ok(value.minimized_kwargs),
                repro_filename: Ok(value.repro_filename),
                run_id: Ok(value.run_id),
                severity: Ok(value.severity),
                shrink_path: Ok(value.shrink_path),
                target_id: Ok(value.target_id),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct DivergenceSummary {
        detail: ::std::result::Result<::std::string::String, ::std::string::String>,
        divergence_class: ::std::result::Result<super::DivergenceClass, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        minimized_args: ::std::result::Result<::std::string::String, ::std::string::String>,
        minimized_kwargs: ::std::result::Result<::std::string::String, ::std::string::String>,
        severity: ::std::result::Result<super::Severity, ::std::string::String>,
        target_id: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for DivergenceSummary {
        fn default() -> Self {
            Self {
                detail: Err("no value supplied for detail".to_string()),
                divergence_class: Err("no value supplied for divergence_class".to_string()),
                id: Err("no value supplied for id".to_string()),
                minimized_args: Err("no value supplied for minimized_args".to_string()),
                minimized_kwargs: Err("no value supplied for minimized_kwargs".to_string()),
                severity: Err("no value supplied for severity".to_string()),
                target_id: Err("no value supplied for target_id".to_string()),
            }
        }
    }
    impl DivergenceSummary {
        pub fn detail<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.detail = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for detail: {e}"));
            self
        }
        pub fn divergence_class<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::DivergenceClass>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_class = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_class: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn minimized_args<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.minimized_args = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for minimized_args: {e}"));
            self
        }
        pub fn minimized_kwargs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.minimized_kwargs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for minimized_kwargs: {e}"));
            self
        }
        pub fn severity<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Severity>,
            T::Error: ::std::fmt::Display,
        {
            self.severity = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for severity: {e}"));
            self
        }
        pub fn target_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.target_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for target_id: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<DivergenceSummary> for super::DivergenceSummary {
        type Error = super::error::ConversionError;
        fn try_from(
            value: DivergenceSummary,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                detail: value.detail?,
                divergence_class: value.divergence_class?,
                id: value.id?,
                minimized_args: value.minimized_args?,
                minimized_kwargs: value.minimized_kwargs?,
                severity: value.severity?,
                target_id: value.target_id?,
            })
        }
    }
    impl ::std::convert::From<super::DivergenceSummary> for DivergenceSummary {
        fn from(value: super::DivergenceSummary) -> Self {
            Self {
                detail: Ok(value.detail),
                divergence_class: Ok(value.divergence_class),
                id: Ok(value.id),
                minimized_args: Ok(value.minimized_args),
                minimized_kwargs: Ok(value.minimized_kwargs),
                severity: Ok(value.severity),
                target_id: Ok(value.target_id),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct ErrorBody {
        code: ::std::result::Result<super::ErrorCode, ::std::string::String>,
        details: ::std::result::Result<
            ::std::option::Option<::serde_json::Map<::std::string::String, ::serde_json::Value>>,
            ::std::string::String,
        >,
        message: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for ErrorBody {
        fn default() -> Self {
            Self {
                code: Err("no value supplied for code".to_string()),
                details: Ok(Default::default()),
                message: Err("no value supplied for message".to_string()),
            }
        }
    }
    impl ErrorBody {
        pub fn code<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::ErrorCode>,
            T::Error: ::std::fmt::Display,
        {
            self.code = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for code: {e}"));
            self
        }
        pub fn details<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<
                ::std::option::Option<
                    ::serde_json::Map<::std::string::String, ::serde_json::Value>,
                >,
            >,
            T::Error: ::std::fmt::Display,
        {
            self.details = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for details: {e}"));
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
    }
    impl ::std::convert::TryFrom<ErrorBody> for super::ErrorBody {
        type Error = super::error::ConversionError;
        fn try_from(
            value: ErrorBody,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                code: value.code?,
                details: value.details?,
                message: value.message?,
            })
        }
    }
    impl ::std::convert::From<super::ErrorBody> for ErrorBody {
        fn from(value: super::ErrorBody) -> Self {
            Self {
                code: Ok(value.code),
                details: Ok(value.details),
                message: Ok(value.message),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct ErrorEnvelope {
        error: ::std::result::Result<super::ErrorBody, ::std::string::String>,
    }
    impl ::std::default::Default for ErrorEnvelope {
        fn default() -> Self {
            Self {
                error: Err("no value supplied for error".to_string()),
            }
        }
    }
    impl ErrorEnvelope {
        pub fn error<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::ErrorBody>,
            T::Error: ::std::fmt::Display,
        {
            self.error = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for error: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<ErrorEnvelope> for super::ErrorEnvelope {
        type Error = super::error::ConversionError;
        fn try_from(
            value: ErrorEnvelope,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                error: value.error?,
            })
        }
    }
    impl ::std::convert::From<super::ErrorEnvelope> for ErrorEnvelope {
        fn from(value: super::ErrorEnvelope) -> Self {
            Self {
                error: Ok(value.error),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct HealthResponse {
        engine_version: ::std::result::Result<::std::string::String, ::std::string::String>,
        schema_version: ::std::result::Result<i32, ::std::string::String>,
        status: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for HealthResponse {
        fn default() -> Self {
            Self {
                engine_version: Err("no value supplied for engine_version".to_string()),
                schema_version: Err("no value supplied for schema_version".to_string()),
                status: Err("no value supplied for status".to_string()),
            }
        }
    }
    impl HealthResponse {
        pub fn engine_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.engine_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for engine_version: {e}"));
            self
        }
        pub fn schema_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.schema_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for schema_version: {e}"));
            self
        }
        pub fn status<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.status = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for status: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<HealthResponse> for super::HealthResponse {
        type Error = super::error::ConversionError;
        fn try_from(
            value: HealthResponse,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                engine_version: value.engine_version?,
                schema_version: value.schema_version?,
                status: value.status?,
            })
        }
    }
    impl ::std::convert::From<super::HealthResponse> for HealthResponse {
        fn from(value: super::HealthResponse) -> Self {
            Self {
                engine_version: Ok(value.engine_version),
                schema_version: Ok(value.schema_version),
                status: Ok(value.status),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct LocalProveRequest {
        base: ::std::result::Result<super::Base, ::std::string::String>,
        head: ::std::result::Result<super::Head, ::std::string::String>,
        max_inputs: ::std::result::Result<i32, ::std::string::String>,
        repo_path: ::std::result::Result<super::RepoPath, ::std::string::String>,
    }
    impl ::std::default::Default for LocalProveRequest {
        fn default() -> Self {
            Self {
                base: Err("no value supplied for base".to_string()),
                head: Err("no value supplied for head".to_string()),
                max_inputs: Ok(super::defaults::default_u64::<i32, 300>()),
                repo_path: Err("no value supplied for repo_path".to_string()),
            }
        }
    }
    impl LocalProveRequest {
        pub fn base<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Base>,
            T::Error: ::std::fmt::Display,
        {
            self.base = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base: {e}"));
            self
        }
        pub fn head<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Head>,
            T::Error: ::std::fmt::Display,
        {
            self.head = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head: {e}"));
            self
        }
        pub fn max_inputs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.max_inputs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for max_inputs: {e}"));
            self
        }
        pub fn repo_path<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::RepoPath>,
            T::Error: ::std::fmt::Display,
        {
            self.repo_path = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for repo_path: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<LocalProveRequest> for super::LocalProveRequest {
        type Error = super::error::ConversionError;
        fn try_from(
            value: LocalProveRequest,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                base: value.base?,
                head: value.head?,
                max_inputs: value.max_inputs?,
                repo_path: value.repo_path?,
            })
        }
    }
    impl ::std::convert::From<super::LocalProveRequest> for LocalProveRequest {
        fn from(value: super::LocalProveRequest) -> Self {
            Self {
                base: Ok(value.base),
                head: Ok(value.head),
                max_inputs: Ok(value.max_inputs),
                repo_path: Ok(value.repo_path),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct LogRecordOut {
        component: ::std::result::Result<::std::string::String, ::std::string::String>,
        level: ::std::result::Result<::std::string::String, ::std::string::String>,
        message: ::std::result::Result<::std::string::String, ::std::string::String>,
        ts: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for LogRecordOut {
        fn default() -> Self {
            Self {
                component: Err("no value supplied for component".to_string()),
                level: Err("no value supplied for level".to_string()),
                message: Err("no value supplied for message".to_string()),
                ts: Err("no value supplied for ts".to_string()),
            }
        }
    }
    impl LogRecordOut {
        pub fn component<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.component = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for component: {e}"));
            self
        }
        pub fn level<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.level = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for level: {e}"));
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
        pub fn ts<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.ts = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for ts: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<LogRecordOut> for super::LogRecordOut {
        type Error = super::error::ConversionError;
        fn try_from(
            value: LogRecordOut,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                component: value.component?,
                level: value.level?,
                message: value.message?,
                ts: value.ts?,
            })
        }
    }
    impl ::std::convert::From<super::LogRecordOut> for LogRecordOut {
        fn from(value: super::LogRecordOut) -> Self {
            Self {
                component: Ok(value.component),
                level: Ok(value.level),
                message: Ok(value.message),
                ts: Ok(value.ts),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct PageRunSummary {
        items: ::std::result::Result<::std::vec::Vec<super::RunSummary>, ::std::string::String>,
        next_cursor: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
    }
    impl ::std::default::Default for PageRunSummary {
        fn default() -> Self {
            Self {
                items: Err("no value supplied for items".to_string()),
                next_cursor: Err("no value supplied for next_cursor".to_string()),
            }
        }
    }
    impl PageRunSummary {
        pub fn items<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<super::RunSummary>>,
            T::Error: ::std::fmt::Display,
        {
            self.items = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for items: {e}"));
            self
        }
        pub fn next_cursor<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.next_cursor = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for next_cursor: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<PageRunSummary> for super::PageRunSummary {
        type Error = super::error::ConversionError;
        fn try_from(
            value: PageRunSummary,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                items: value.items?,
                next_cursor: value.next_cursor?,
            })
        }
    }
    impl ::std::convert::From<super::PageRunSummary> for PageRunSummary {
        fn from(value: super::PageRunSummary) -> Self {
            Self {
                items: Ok(value.items),
                next_cursor: Ok(value.next_cursor),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct RunCreate {
        base_sha: ::std::result::Result<super::BaseSha, ::std::string::String>,
        head_sha: ::std::result::Result<super::HeadSha, ::std::string::String>,
        repo: ::std::result::Result<super::Repo, ::std::string::String>,
    }
    impl ::std::default::Default for RunCreate {
        fn default() -> Self {
            Self {
                base_sha: Err("no value supplied for base_sha".to_string()),
                head_sha: Err("no value supplied for head_sha".to_string()),
                repo: Err("no value supplied for repo".to_string()),
            }
        }
    }
    impl RunCreate {
        pub fn base_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::BaseSha>,
            T::Error: ::std::fmt::Display,
        {
            self.base_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base_sha: {e}"));
            self
        }
        pub fn head_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::HeadSha>,
            T::Error: ::std::fmt::Display,
        {
            self.head_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head_sha: {e}"));
            self
        }
        pub fn repo<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Repo>,
            T::Error: ::std::fmt::Display,
        {
            self.repo = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for repo: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<RunCreate> for super::RunCreate {
        type Error = super::error::ConversionError;
        fn try_from(
            value: RunCreate,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                base_sha: value.base_sha?,
                head_sha: value.head_sha?,
                repo: value.repo?,
            })
        }
    }
    impl ::std::convert::From<super::RunCreate> for RunCreate {
        fn from(value: super::RunCreate) -> Self {
            Self {
                base_sha: Ok(value.base_sha),
                head_sha: Ok(value.head_sha),
                repo: Ok(value.repo),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct RunCreated {
        run_id: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for RunCreated {
        fn default() -> Self {
            Self {
                run_id: Err("no value supplied for run_id".to_string()),
            }
        }
    }
    impl RunCreated {
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<RunCreated> for super::RunCreated {
        type Error = super::error::ConversionError;
        fn try_from(
            value: RunCreated,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                run_id: value.run_id?,
            })
        }
    }
    impl ::std::convert::From<super::RunCreated> for RunCreated {
        fn from(value: super::RunCreated) -> Self {
            Self {
                run_id: Ok(value.run_id),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct RunDetail {
        base_deps: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        base_sha: ::std::result::Result<::std::string::String, ::std::string::String>,
        budget_max_inputs: ::std::result::Result<::std::option::Option<i32>, ::std::string::String>,
        bundle_created_at: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        created_at:
            ::std::result::Result<::chrono::DateTime<::chrono::offset::Utc>, ::std::string::String>,
        divergence_count: ::std::result::Result<i32, ::std::string::String>,
        engine_version: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        head_deps: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        head_sha: ::std::result::Result<::std::string::String, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        repo: ::std::result::Result<::std::string::String, ::std::string::String>,
        sandbox_assurance: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        sandbox_tier: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        schema_version: ::std::result::Result<::std::option::Option<i32>, ::std::string::String>,
        status: ::std::result::Result<super::RunStatus, ::std::string::String>,
        target_count: ::std::result::Result<i32, ::std::string::String>,
        targets:
            ::std::result::Result<::std::vec::Vec<super::TargetSummary>, ::std::string::String>,
        verdict:
            ::std::result::Result<::std::option::Option<super::Verdict>, ::std::string::String>,
    }
    impl ::std::default::Default for RunDetail {
        fn default() -> Self {
            Self {
                base_deps: Err("no value supplied for base_deps".to_string()),
                base_sha: Err("no value supplied for base_sha".to_string()),
                budget_max_inputs: Err("no value supplied for budget_max_inputs".to_string()),
                bundle_created_at: Err("no value supplied for bundle_created_at".to_string()),
                created_at: Err("no value supplied for created_at".to_string()),
                divergence_count: Err("no value supplied for divergence_count".to_string()),
                engine_version: Err("no value supplied for engine_version".to_string()),
                head_deps: Err("no value supplied for head_deps".to_string()),
                head_sha: Err("no value supplied for head_sha".to_string()),
                id: Err("no value supplied for id".to_string()),
                repo: Err("no value supplied for repo".to_string()),
                sandbox_assurance: Err("no value supplied for sandbox_assurance".to_string()),
                sandbox_tier: Err("no value supplied for sandbox_tier".to_string()),
                schema_version: Err("no value supplied for schema_version".to_string()),
                status: Err("no value supplied for status".to_string()),
                target_count: Err("no value supplied for target_count".to_string()),
                targets: Err("no value supplied for targets".to_string()),
                verdict: Err("no value supplied for verdict".to_string()),
            }
        }
    }
    impl RunDetail {
        pub fn base_deps<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.base_deps = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base_deps: {e}"));
            self
        }
        pub fn base_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.base_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base_sha: {e}"));
            self
        }
        pub fn budget_max_inputs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<i32>>,
            T::Error: ::std::fmt::Display,
        {
            self.budget_max_inputs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for budget_max_inputs: {e}"));
            self
        }
        pub fn bundle_created_at<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.bundle_created_at = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for bundle_created_at: {e}"));
            self
        }
        pub fn created_at<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::chrono::DateTime<::chrono::offset::Utc>>,
            T::Error: ::std::fmt::Display,
        {
            self.created_at = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for created_at: {e}"));
            self
        }
        pub fn divergence_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_count: {e}"));
            self
        }
        pub fn engine_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.engine_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for engine_version: {e}"));
            self
        }
        pub fn head_deps<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.head_deps = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head_deps: {e}"));
            self
        }
        pub fn head_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.head_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head_sha: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn repo<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.repo = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for repo: {e}"));
            self
        }
        pub fn sandbox_assurance<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.sandbox_assurance = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for sandbox_assurance: {e}"));
            self
        }
        pub fn sandbox_tier<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.sandbox_tier = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for sandbox_tier: {e}"));
            self
        }
        pub fn schema_version<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<i32>>,
            T::Error: ::std::fmt::Display,
        {
            self.schema_version = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for schema_version: {e}"));
            self
        }
        pub fn status<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::RunStatus>,
            T::Error: ::std::fmt::Display,
        {
            self.status = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for status: {e}"));
            self
        }
        pub fn target_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.target_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for target_count: {e}"));
            self
        }
        pub fn targets<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<super::TargetSummary>>,
            T::Error: ::std::fmt::Display,
        {
            self.targets = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for targets: {e}"));
            self
        }
        pub fn verdict<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<super::Verdict>>,
            T::Error: ::std::fmt::Display,
        {
            self.verdict = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for verdict: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<RunDetail> for super::RunDetail {
        type Error = super::error::ConversionError;
        fn try_from(
            value: RunDetail,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                base_deps: value.base_deps?,
                base_sha: value.base_sha?,
                budget_max_inputs: value.budget_max_inputs?,
                bundle_created_at: value.bundle_created_at?,
                created_at: value.created_at?,
                divergence_count: value.divergence_count?,
                engine_version: value.engine_version?,
                head_deps: value.head_deps?,
                head_sha: value.head_sha?,
                id: value.id?,
                repo: value.repo?,
                sandbox_assurance: value.sandbox_assurance?,
                sandbox_tier: value.sandbox_tier?,
                schema_version: value.schema_version?,
                status: value.status?,
                target_count: value.target_count?,
                targets: value.targets?,
                verdict: value.verdict?,
            })
        }
    }
    impl ::std::convert::From<super::RunDetail> for RunDetail {
        fn from(value: super::RunDetail) -> Self {
            Self {
                base_deps: Ok(value.base_deps),
                base_sha: Ok(value.base_sha),
                budget_max_inputs: Ok(value.budget_max_inputs),
                bundle_created_at: Ok(value.bundle_created_at),
                created_at: Ok(value.created_at),
                divergence_count: Ok(value.divergence_count),
                engine_version: Ok(value.engine_version),
                head_deps: Ok(value.head_deps),
                head_sha: Ok(value.head_sha),
                id: Ok(value.id),
                repo: Ok(value.repo),
                sandbox_assurance: Ok(value.sandbox_assurance),
                sandbox_tier: Ok(value.sandbox_tier),
                schema_version: Ok(value.schema_version),
                status: Ok(value.status),
                target_count: Ok(value.target_count),
                targets: Ok(value.targets),
                verdict: Ok(value.verdict),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct RunEventOut {
        level: ::std::result::Result<::std::string::String, ::std::string::String>,
        message: ::std::result::Result<::std::string::String, ::std::string::String>,
        stage: ::std::result::Result<::std::string::String, ::std::string::String>,
        ts: ::std::result::Result<::chrono::DateTime<::chrono::offset::Utc>, ::std::string::String>,
    }
    impl ::std::default::Default for RunEventOut {
        fn default() -> Self {
            Self {
                level: Err("no value supplied for level".to_string()),
                message: Err("no value supplied for message".to_string()),
                stage: Err("no value supplied for stage".to_string()),
                ts: Err("no value supplied for ts".to_string()),
            }
        }
    }
    impl RunEventOut {
        pub fn level<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.level = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for level: {e}"));
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
        pub fn stage<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.stage = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for stage: {e}"));
            self
        }
        pub fn ts<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::chrono::DateTime<::chrono::offset::Utc>>,
            T::Error: ::std::fmt::Display,
        {
            self.ts = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for ts: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<RunEventOut> for super::RunEventOut {
        type Error = super::error::ConversionError;
        fn try_from(
            value: RunEventOut,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                level: value.level?,
                message: value.message?,
                stage: value.stage?,
                ts: value.ts?,
            })
        }
    }
    impl ::std::convert::From<super::RunEventOut> for RunEventOut {
        fn from(value: super::RunEventOut) -> Self {
            Self {
                level: Ok(value.level),
                message: Ok(value.message),
                stage: Ok(value.stage),
                ts: Ok(value.ts),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct RunSummary {
        base_sha: ::std::result::Result<::std::string::String, ::std::string::String>,
        created_at:
            ::std::result::Result<::chrono::DateTime<::chrono::offset::Utc>, ::std::string::String>,
        divergence_count: ::std::result::Result<i32, ::std::string::String>,
        head_sha: ::std::result::Result<::std::string::String, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        repo: ::std::result::Result<::std::string::String, ::std::string::String>,
        status: ::std::result::Result<super::RunStatus, ::std::string::String>,
        target_count: ::std::result::Result<i32, ::std::string::String>,
        verdict:
            ::std::result::Result<::std::option::Option<super::Verdict>, ::std::string::String>,
    }
    impl ::std::default::Default for RunSummary {
        fn default() -> Self {
            Self {
                base_sha: Err("no value supplied for base_sha".to_string()),
                created_at: Err("no value supplied for created_at".to_string()),
                divergence_count: Err("no value supplied for divergence_count".to_string()),
                head_sha: Err("no value supplied for head_sha".to_string()),
                id: Err("no value supplied for id".to_string()),
                repo: Err("no value supplied for repo".to_string()),
                status: Err("no value supplied for status".to_string()),
                target_count: Err("no value supplied for target_count".to_string()),
                verdict: Err("no value supplied for verdict".to_string()),
            }
        }
    }
    impl RunSummary {
        pub fn base_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.base_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for base_sha: {e}"));
            self
        }
        pub fn created_at<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::chrono::DateTime<::chrono::offset::Utc>>,
            T::Error: ::std::fmt::Display,
        {
            self.created_at = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for created_at: {e}"));
            self
        }
        pub fn divergence_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_count: {e}"));
            self
        }
        pub fn head_sha<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.head_sha = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for head_sha: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn repo<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.repo = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for repo: {e}"));
            self
        }
        pub fn status<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::RunStatus>,
            T::Error: ::std::fmt::Display,
        {
            self.status = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for status: {e}"));
            self
        }
        pub fn target_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.target_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for target_count: {e}"));
            self
        }
        pub fn verdict<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<super::Verdict>>,
            T::Error: ::std::fmt::Display,
        {
            self.verdict = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for verdict: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<RunSummary> for super::RunSummary {
        type Error = super::error::ConversionError;
        fn try_from(
            value: RunSummary,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                base_sha: value.base_sha?,
                created_at: value.created_at?,
                divergence_count: value.divergence_count?,
                head_sha: value.head_sha?,
                id: value.id?,
                repo: value.repo?,
                status: value.status?,
                target_count: value.target_count?,
                verdict: value.verdict?,
            })
        }
    }
    impl ::std::convert::From<super::RunSummary> for RunSummary {
        fn from(value: super::RunSummary) -> Self {
            Self {
                base_sha: Ok(value.base_sha),
                created_at: Ok(value.created_at),
                divergence_count: Ok(value.divergence_count),
                head_sha: Ok(value.head_sha),
                id: Ok(value.id),
                repo: Ok(value.repo),
                status: Ok(value.status),
                target_count: Ok(value.target_count),
                verdict: Ok(value.verdict),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct SearchHit {
        divergence_class: ::std::result::Result<super::DivergenceClass, ::std::string::String>,
        divergence_id: ::std::result::Result<i32, ::std::string::String>,
        module: ::std::result::Result<::std::string::String, ::std::string::String>,
        qualname: ::std::result::Result<::std::string::String, ::std::string::String>,
        run_id: ::std::result::Result<i32, ::std::string::String>,
        severity: ::std::result::Result<super::Severity, ::std::string::String>,
        snippet: ::std::result::Result<::std::string::String, ::std::string::String>,
        target_id: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for SearchHit {
        fn default() -> Self {
            Self {
                divergence_class: Err("no value supplied for divergence_class".to_string()),
                divergence_id: Err("no value supplied for divergence_id".to_string()),
                module: Err("no value supplied for module".to_string()),
                qualname: Err("no value supplied for qualname".to_string()),
                run_id: Err("no value supplied for run_id".to_string()),
                severity: Err("no value supplied for severity".to_string()),
                snippet: Err("no value supplied for snippet".to_string()),
                target_id: Err("no value supplied for target_id".to_string()),
            }
        }
    }
    impl SearchHit {
        pub fn divergence_class<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::DivergenceClass>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_class = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_class: {e}"));
            self
        }
        pub fn divergence_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_id: {e}"));
            self
        }
        pub fn module<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.module = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for module: {e}"));
            self
        }
        pub fn qualname<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.qualname = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for qualname: {e}"));
            self
        }
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
        pub fn severity<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Severity>,
            T::Error: ::std::fmt::Display,
        {
            self.severity = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for severity: {e}"));
            self
        }
        pub fn snippet<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.snippet = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for snippet: {e}"));
            self
        }
        pub fn target_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.target_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for target_id: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<SearchHit> for super::SearchHit {
        type Error = super::error::ConversionError;
        fn try_from(
            value: SearchHit,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                divergence_class: value.divergence_class?,
                divergence_id: value.divergence_id?,
                module: value.module?,
                qualname: value.qualname?,
                run_id: value.run_id?,
                severity: value.severity?,
                snippet: value.snippet?,
                target_id: value.target_id?,
            })
        }
    }
    impl ::std::convert::From<super::SearchHit> for SearchHit {
        fn from(value: super::SearchHit) -> Self {
            Self {
                divergence_class: Ok(value.divergence_class),
                divergence_id: Ok(value.divergence_id),
                module: Ok(value.module),
                qualname: Ok(value.qualname),
                run_id: Ok(value.run_id),
                severity: Ok(value.severity),
                snippet: Ok(value.snippet),
                target_id: Ok(value.target_id),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct SearchResults {
        hits: ::std::result::Result<::std::vec::Vec<super::SearchHit>, ::std::string::String>,
        query: ::std::result::Result<::std::string::String, ::std::string::String>,
    }
    impl ::std::default::Default for SearchResults {
        fn default() -> Self {
            Self {
                hits: Err("no value supplied for hits".to_string()),
                query: Err("no value supplied for query".to_string()),
            }
        }
    }
    impl SearchResults {
        pub fn hits<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<super::SearchHit>>,
            T::Error: ::std::fmt::Display,
        {
            self.hits = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for hits: {e}"));
            self
        }
        pub fn query<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.query = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for query: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<SearchResults> for super::SearchResults {
        type Error = super::error::ConversionError;
        fn try_from(
            value: SearchResults,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                hits: value.hits?,
                query: value.query?,
            })
        }
    }
    impl ::std::convert::From<super::SearchResults> for SearchResults {
        fn from(value: super::SearchResults) -> Self {
            Self {
                hits: Ok(value.hits),
                query: Ok(value.query),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct SyncPushRequest {
        server_url: ::std::result::Result<super::ServerUrl, ::std::string::String>,
    }
    impl ::std::default::Default for SyncPushRequest {
        fn default() -> Self {
            Self {
                server_url: Err("no value supplied for server_url".to_string()),
            }
        }
    }
    impl SyncPushRequest {
        pub fn server_url<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::ServerUrl>,
            T::Error: ::std::fmt::Display,
        {
            self.server_url = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for server_url: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<SyncPushRequest> for super::SyncPushRequest {
        type Error = super::error::ConversionError;
        fn try_from(
            value: SyncPushRequest,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                server_url: value.server_url?,
            })
        }
    }
    impl ::std::convert::From<super::SyncPushRequest> for SyncPushRequest {
        fn from(value: super::SyncPushRequest) -> Self {
            Self {
                server_url: Ok(value.server_url),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct SyncReport {
        candidates: ::std::result::Result<i32, ::std::string::String>,
        errors:
            ::std::result::Result<::std::vec::Vec<::std::string::String>, ::std::string::String>,
        failed: ::std::result::Result<i32, ::std::string::String>,
        pushed: ::std::result::Result<i32, ::std::string::String>,
        remaining: ::std::result::Result<i32, ::std::string::String>,
        skipped: ::std::result::Result<i32, ::std::string::String>,
    }
    impl ::std::default::Default for SyncReport {
        fn default() -> Self {
            Self {
                candidates: Err("no value supplied for candidates".to_string()),
                errors: Err("no value supplied for errors".to_string()),
                failed: Err("no value supplied for failed".to_string()),
                pushed: Err("no value supplied for pushed".to_string()),
                remaining: Err("no value supplied for remaining".to_string()),
                skipped: Err("no value supplied for skipped".to_string()),
            }
        }
    }
    impl SyncReport {
        pub fn candidates<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.candidates = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for candidates: {e}"));
            self
        }
        pub fn errors<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.errors = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for errors: {e}"));
            self
        }
        pub fn failed<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.failed = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for failed: {e}"));
            self
        }
        pub fn pushed<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.pushed = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for pushed: {e}"));
            self
        }
        pub fn remaining<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.remaining = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for remaining: {e}"));
            self
        }
        pub fn skipped<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.skipped = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for skipped: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<SyncReport> for super::SyncReport {
        type Error = super::error::ConversionError;
        fn try_from(
            value: SyncReport,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                candidates: value.candidates?,
                errors: value.errors?,
                failed: value.failed?,
                pushed: value.pushed?,
                remaining: value.remaining?,
                skipped: value.skipped?,
            })
        }
    }
    impl ::std::convert::From<super::SyncReport> for SyncReport {
        fn from(value: super::SyncReport) -> Self {
            Self {
                candidates: Ok(value.candidates),
                errors: Ok(value.errors),
                failed: Ok(value.failed),
                pushed: Ok(value.pushed),
                remaining: Ok(value.remaining),
                skipped: Ok(value.skipped),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct TargetDetail {
        changed_line_coverage: ::std::result::Result<f64, ::std::string::String>,
        classification: ::std::result::Result<super::TargetClassification, ::std::string::String>,
        divergence_count: ::std::result::Result<i32, ::std::string::String>,
        divergences:
            ::std::result::Result<::std::vec::Vec<super::DivergenceSummary>, ::std::string::String>,
        equivalent_inputs: ::std::result::Result<i32, ::std::string::String>,
        file_path: ::std::result::Result<::std::string::String, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        inputs_run: ::std::result::Result<i32, ::std::string::String>,
        lang: ::std::result::Result<super::Lang, ::std::string::String>,
        module: ::std::result::Result<::std::string::String, ::std::string::String>,
        qualname: ::std::result::Result<::std::string::String, ::std::string::String>,
        reason_code:
            ::std::result::Result<::std::option::Option<super::ReasonCode>, ::std::string::String>,
        reason_detail: ::std::result::Result<
            ::std::option::Option<::std::string::String>,
            ::std::string::String,
        >,
        run_id: ::std::result::Result<i32, ::std::string::String>,
        unprovable_inputs: ::std::result::Result<i32, ::std::string::String>,
        verdict: ::std::result::Result<super::Verdict, ::std::string::String>,
    }
    impl ::std::default::Default for TargetDetail {
        fn default() -> Self {
            Self {
                changed_line_coverage: Err(
                    "no value supplied for changed_line_coverage".to_string()
                ),
                classification: Err("no value supplied for classification".to_string()),
                divergence_count: Err("no value supplied for divergence_count".to_string()),
                divergences: Err("no value supplied for divergences".to_string()),
                equivalent_inputs: Err("no value supplied for equivalent_inputs".to_string()),
                file_path: Err("no value supplied for file_path".to_string()),
                id: Err("no value supplied for id".to_string()),
                inputs_run: Err("no value supplied for inputs_run".to_string()),
                lang: Err("no value supplied for lang".to_string()),
                module: Err("no value supplied for module".to_string()),
                qualname: Err("no value supplied for qualname".to_string()),
                reason_code: Err("no value supplied for reason_code".to_string()),
                reason_detail: Err("no value supplied for reason_detail".to_string()),
                run_id: Err("no value supplied for run_id".to_string()),
                unprovable_inputs: Err("no value supplied for unprovable_inputs".to_string()),
                verdict: Err("no value supplied for verdict".to_string()),
            }
        }
    }
    impl TargetDetail {
        pub fn changed_line_coverage<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<f64>,
            T::Error: ::std::fmt::Display,
        {
            self.changed_line_coverage = value.try_into().map_err(|e| {
                format!("error converting supplied value for changed_line_coverage: {e}")
            });
            self
        }
        pub fn classification<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::TargetClassification>,
            T::Error: ::std::fmt::Display,
        {
            self.classification = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for classification: {e}"));
            self
        }
        pub fn divergence_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_count: {e}"));
            self
        }
        pub fn divergences<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::vec::Vec<super::DivergenceSummary>>,
            T::Error: ::std::fmt::Display,
        {
            self.divergences = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergences: {e}"));
            self
        }
        pub fn equivalent_inputs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.equivalent_inputs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for equivalent_inputs: {e}"));
            self
        }
        pub fn file_path<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.file_path = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for file_path: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn inputs_run<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.inputs_run = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for inputs_run: {e}"));
            self
        }
        pub fn lang<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Lang>,
            T::Error: ::std::fmt::Display,
        {
            self.lang = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for lang: {e}"));
            self
        }
        pub fn module<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.module = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for module: {e}"));
            self
        }
        pub fn qualname<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.qualname = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for qualname: {e}"));
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
        pub fn reason_detail<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::option::Option<::std::string::String>>,
            T::Error: ::std::fmt::Display,
        {
            self.reason_detail = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for reason_detail: {e}"));
            self
        }
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
        pub fn unprovable_inputs<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.unprovable_inputs = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for unprovable_inputs: {e}"));
            self
        }
        pub fn verdict<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Verdict>,
            T::Error: ::std::fmt::Display,
        {
            self.verdict = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for verdict: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<TargetDetail> for super::TargetDetail {
        type Error = super::error::ConversionError;
        fn try_from(
            value: TargetDetail,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                changed_line_coverage: value.changed_line_coverage?,
                classification: value.classification?,
                divergence_count: value.divergence_count?,
                divergences: value.divergences?,
                equivalent_inputs: value.equivalent_inputs?,
                file_path: value.file_path?,
                id: value.id?,
                inputs_run: value.inputs_run?,
                lang: value.lang?,
                module: value.module?,
                qualname: value.qualname?,
                reason_code: value.reason_code?,
                reason_detail: value.reason_detail?,
                run_id: value.run_id?,
                unprovable_inputs: value.unprovable_inputs?,
                verdict: value.verdict?,
            })
        }
    }
    impl ::std::convert::From<super::TargetDetail> for TargetDetail {
        fn from(value: super::TargetDetail) -> Self {
            Self {
                changed_line_coverage: Ok(value.changed_line_coverage),
                classification: Ok(value.classification),
                divergence_count: Ok(value.divergence_count),
                divergences: Ok(value.divergences),
                equivalent_inputs: Ok(value.equivalent_inputs),
                file_path: Ok(value.file_path),
                id: Ok(value.id),
                inputs_run: Ok(value.inputs_run),
                lang: Ok(value.lang),
                module: Ok(value.module),
                qualname: Ok(value.qualname),
                reason_code: Ok(value.reason_code),
                reason_detail: Ok(value.reason_detail),
                run_id: Ok(value.run_id),
                unprovable_inputs: Ok(value.unprovable_inputs),
                verdict: Ok(value.verdict),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct TargetSummary {
        changed_line_coverage: ::std::result::Result<f64, ::std::string::String>,
        classification: ::std::result::Result<super::TargetClassification, ::std::string::String>,
        divergence_count: ::std::result::Result<i32, ::std::string::String>,
        file_path: ::std::result::Result<::std::string::String, ::std::string::String>,
        id: ::std::result::Result<i32, ::std::string::String>,
        lang: ::std::result::Result<super::Lang, ::std::string::String>,
        module: ::std::result::Result<::std::string::String, ::std::string::String>,
        qualname: ::std::result::Result<::std::string::String, ::std::string::String>,
        reason_code:
            ::std::result::Result<::std::option::Option<super::ReasonCode>, ::std::string::String>,
        run_id: ::std::result::Result<i32, ::std::string::String>,
        verdict: ::std::result::Result<super::Verdict, ::std::string::String>,
    }
    impl ::std::default::Default for TargetSummary {
        fn default() -> Self {
            Self {
                changed_line_coverage: Err(
                    "no value supplied for changed_line_coverage".to_string()
                ),
                classification: Err("no value supplied for classification".to_string()),
                divergence_count: Err("no value supplied for divergence_count".to_string()),
                file_path: Err("no value supplied for file_path".to_string()),
                id: Err("no value supplied for id".to_string()),
                lang: Err("no value supplied for lang".to_string()),
                module: Err("no value supplied for module".to_string()),
                qualname: Err("no value supplied for qualname".to_string()),
                reason_code: Err("no value supplied for reason_code".to_string()),
                run_id: Err("no value supplied for run_id".to_string()),
                verdict: Err("no value supplied for verdict".to_string()),
            }
        }
    }
    impl TargetSummary {
        pub fn changed_line_coverage<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<f64>,
            T::Error: ::std::fmt::Display,
        {
            self.changed_line_coverage = value.try_into().map_err(|e| {
                format!("error converting supplied value for changed_line_coverage: {e}")
            });
            self
        }
        pub fn classification<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::TargetClassification>,
            T::Error: ::std::fmt::Display,
        {
            self.classification = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for classification: {e}"));
            self
        }
        pub fn divergence_count<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.divergence_count = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for divergence_count: {e}"));
            self
        }
        pub fn file_path<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.file_path = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for file_path: {e}"));
            self
        }
        pub fn id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for id: {e}"));
            self
        }
        pub fn lang<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Lang>,
            T::Error: ::std::fmt::Display,
        {
            self.lang = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for lang: {e}"));
            self
        }
        pub fn module<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.module = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for module: {e}"));
            self
        }
        pub fn qualname<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<::std::string::String>,
            T::Error: ::std::fmt::Display,
        {
            self.qualname = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for qualname: {e}"));
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
        pub fn run_id<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<i32>,
            T::Error: ::std::fmt::Display,
        {
            self.run_id = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for run_id: {e}"));
            self
        }
        pub fn verdict<T>(mut self, value: T) -> Self
        where
            T: ::std::convert::TryInto<super::Verdict>,
            T::Error: ::std::fmt::Display,
        {
            self.verdict = value
                .try_into()
                .map_err(|e| format!("error converting supplied value for verdict: {e}"));
            self
        }
    }
    impl ::std::convert::TryFrom<TargetSummary> for super::TargetSummary {
        type Error = super::error::ConversionError;
        fn try_from(
            value: TargetSummary,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {
                changed_line_coverage: value.changed_line_coverage?,
                classification: value.classification?,
                divergence_count: value.divergence_count?,
                file_path: value.file_path?,
                id: value.id?,
                lang: value.lang?,
                module: value.module?,
                qualname: value.qualname?,
                reason_code: value.reason_code?,
                run_id: value.run_id?,
                verdict: value.verdict?,
            })
        }
    }
    impl ::std::convert::From<super::TargetSummary> for TargetSummary {
        fn from(value: super::TargetSummary) -> Self {
            Self {
                changed_line_coverage: Ok(value.changed_line_coverage),
                classification: Ok(value.classification),
                divergence_count: Ok(value.divergence_count),
                file_path: Ok(value.file_path),
                id: Ok(value.id),
                lang: Ok(value.lang),
                module: Ok(value.module),
                qualname: Ok(value.qualname),
                reason_code: Ok(value.reason_code),
                run_id: Ok(value.run_id),
                verdict: Ok(value.verdict),
            }
        }
    }
    #[derive(Clone, Debug)]
    pub struct TempestDomain {}
    impl ::std::default::Default for TempestDomain {
        fn default() -> Self {
            Self {}
        }
    }
    impl TempestDomain {}
    impl ::std::convert::TryFrom<TempestDomain> for super::TempestDomain {
        type Error = super::error::ConversionError;
        fn try_from(
            _value: TempestDomain,
        ) -> ::std::result::Result<Self, super::error::ConversionError> {
            Ok(Self {})
        }
    }
    impl ::std::convert::From<super::TempestDomain> for TempestDomain {
        fn from(_value: super::TempestDomain) -> Self {
            Self {}
        }
    }
}
#[doc = r" Generation of default values for serde."]
pub mod defaults {
    pub(super) fn default_u64<T, const V: u64>() -> T
    where
        T: ::std::convert::TryFrom<u64>,
        <T as ::std::convert::TryFrom<u64>>::Error: ::std::fmt::Debug,
    {
        T::try_from(V).unwrap()
    }
}
