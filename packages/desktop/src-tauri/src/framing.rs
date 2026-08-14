//! Boundary A framing (CLAUDE.md §9b): `Content-Length: <n>\r\n\r\n<n bytes>` over any
//! byte stream. Mirrors `tempest_api.stdiorpc` exactly — the two codecs are property-tested
//! against each other by the py↔rust round-trip gate.

use std::io::{BufRead, Write};

/// A bundle-sized payload fits; a runaway peer does not.
pub const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;
const MAX_HEADER_BYTES: usize = 8192;

#[derive(Debug)]
pub enum FrameError {
    /// The peer closed the stream at a clean frame boundary.
    Eof,
    /// The byte stream stopped being a valid frame sequence — unrecoverable.
    Protocol(String),
    Io(std::io::Error),
}

impl std::fmt::Display for FrameError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FrameError::Eof => write!(f, "peer closed the frame stream"),
            FrameError::Protocol(message) => write!(f, "framing protocol error: {message}"),
            FrameError::Io(err) => write!(f, "frame io error: {err}"),
        }
    }
}

impl std::error::Error for FrameError {}

impl From<std::io::Error> for FrameError {
    fn from(err: std::io::Error) -> Self {
        FrameError::Io(err)
    }
}

pub fn write_frame(stream: &mut impl Write, payload: &[u8]) -> Result<(), FrameError> {
    stream.write_all(format!("Content-Length: {}\r\n\r\n", payload.len()).as_bytes())?;
    stream.write_all(payload)?;
    stream.flush()?;
    Ok(())
}

pub fn read_frame(stream: &mut impl BufRead) -> Result<Vec<u8>, FrameError> {
    let mut header: Vec<u8> = Vec::new();
    while !header.ends_with(b"\r\n\r\n") {
        let mut byte = [0u8; 1];
        match stream.read(&mut byte)? {
            0 if header.is_empty() => return Err(FrameError::Eof),
            0 => return Err(FrameError::Protocol("EOF inside frame header".into())),
            _ => header.push(byte[0]),
        }
        if header.len() > MAX_HEADER_BYTES {
            return Err(FrameError::Protocol("frame header exceeds 8 KiB".into()));
        }
    }
    let mut length: Option<usize> = None;
    for line in header[..header.len() - 4].split(|&b| b == b'\r') {
        let line = line.strip_prefix(b"\n").unwrap_or(line);
        if let Some((name, value)) = split_header(line) {
            if name.eq_ignore_ascii_case("content-length") {
                length = Some(
                    value
                        .trim()
                        .parse::<usize>()
                        .map_err(|_| FrameError::Protocol(format!("bad Content-Length {value:?}")))?,
                );
            }
        }
    }
    let length =
        length.ok_or_else(|| FrameError::Protocol("frame missing Content-Length".into()))?;
    if length > MAX_FRAME_BYTES {
        return Err(FrameError::Protocol(format!(
            "frame length {length} exceeds {MAX_FRAME_BYTES}"
        )));
    }
    let mut payload = vec![0u8; length];
    stream
        .read_exact(&mut payload)
        .map_err(|err| match err.kind() {
            std::io::ErrorKind::UnexpectedEof => {
                FrameError::Protocol("EOF inside frame payload".into())
            }
            _ => FrameError::Io(err),
        })?;
    Ok(payload)
}

fn split_header(line: &[u8]) -> Option<(&str, &str)> {
    let text = std::str::from_utf8(line).ok()?;
    let (name, value) = text.split_once(':')?;
    Some((name.trim(), value))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn round_trips_frames() {
        let mut buffer: Vec<u8> = Vec::new();
        write_frame(&mut buffer, br#"{"jsonrpc":"2.0"}"#).unwrap();
        write_frame(&mut buffer, "unicode: ⛈".as_bytes()).unwrap();
        let mut cursor = Cursor::new(buffer);
        assert_eq!(read_frame(&mut cursor).unwrap(), br#"{"jsonrpc":"2.0"}"#);
        assert_eq!(read_frame(&mut cursor).unwrap(), "unicode: ⛈".as_bytes());
        assert!(matches!(read_frame(&mut cursor), Err(FrameError::Eof)));
    }

    #[test]
    fn eof_inside_header_is_protocol_error() {
        let mut cursor = Cursor::new(b"Content-Length: 10\r\n".to_vec());
        assert!(matches!(read_frame(&mut cursor), Err(FrameError::Protocol(_))));
    }

    #[test]
    fn eof_inside_payload_is_protocol_error() {
        let mut cursor = Cursor::new(b"Content-Length: 10\r\n\r\nabc".to_vec());
        assert!(matches!(read_frame(&mut cursor), Err(FrameError::Protocol(_))));
    }

    #[test]
    fn missing_length_is_protocol_error() {
        let mut cursor = Cursor::new(b"X-Other: 1\r\n\r\n".to_vec());
        assert!(matches!(read_frame(&mut cursor), Err(FrameError::Protocol(_))));
    }

    #[test]
    fn absurd_length_is_protocol_error() {
        let mut cursor = Cursor::new(b"Content-Length: 999999999999\r\n\r\n".to_vec());
        assert!(matches!(read_frame(&mut cursor), Err(FrameError::Protocol(_))));
    }
}
