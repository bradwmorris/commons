//! One canonical, locally tokenized Object packet. Never split or truncate writes.
use crate::{Result, invalid};
use std::sync::OnceLock;
use tokenizers::Tokenizer;

pub const LIMIT: usize = 500;
pub const TOKENIZER_SHA256: &str =
    "4d777ef5bdc1aa36227abdfb77c3e49e7b9c892d16e1b6bda41c393504828be4";
static TOKENIZER: OnceLock<Tokenizer> = OnceLock::new();

pub fn input(title: &str, description: &str, body: &str) -> String {
    format!("title: {title} | text: {description}\n\n{body}")
}

pub fn count(title: &str, description: &str, body: &str) -> Result<usize> {
    let tokenizer = TOKENIZER.get_or_init(|| {
        let bytes = include_bytes!("../assets/embeddinggemma2-tokenizer.json");
        assert_eq!(
            format!("{:x}", <sha2::Sha256 as sha2::Digest>::digest(bytes)),
            TOKENIZER_SHA256
        );
        let mut tokenizer = Tokenizer::from_bytes(bytes).expect("pinned tokenizer is valid");
        tokenizer
            .with_truncation(None)
            .expect("no tokenizer truncation");
        tokenizer.with_padding(None);
        tokenizer
    });
    tokenizer
        .encode(input(title, description, body), true)
        .map(|encoding| encoding.len())
        .map_err(|_| invalid("Object tokenization failed; not saved"))
}

pub fn validate(title: &str, description: &str, body: &str) -> Result<usize> {
    if title.trim().is_empty() || title.contains(['\n', '\r']) || title.chars().count() > 200 {
        return Err(invalid(
            "Not saved: title must be one nonempty line, at most 200 characters",
        ));
    }
    if description.trim().is_empty() || description.chars().count() > 600 {
        return Err(invalid(
            "Not saved: description is required, at most 600 characters; state plainly what this record is",
        ));
    }
    if body.len() > 32768 {
        return Err(invalid(
            "Not saved: body exceeds 32 KiB; long content belongs in an Artifact",
        ));
    }
    let tokens = count(title, description, body)?;
    if tokens > LIMIT {
        return Err(invalid(&format!(
            "Not saved: Object uses {tokens} tokens; limit is {LIMIT}, including title, description, body and embedding formatting. Shorten it or move extended material to an Artifact."
        )));
    }
    Ok(tokens)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_formatted_packet_without_inference_or_truncation() {
        let n = count(
            "Atomic objects",
            "A rule requiring one idea per Object.",
            "",
        )
        .unwrap();
        assert!(n > 0 && n < LIMIT);
        let long = "A qualification that must remain intact. ".repeat(600);
        assert!(
            count(
                "Atomic objects",
                "A rule requiring one idea per Object.",
                &long
            )
            .unwrap()
                > LIMIT
        );
        assert!(
            validate(
                "Atomic objects",
                "A rule requiring one idea per Object.",
                &long
            )
            .is_err()
        );
        assert!(validate("Bad\ntitle", "A rule.", "").is_err());
        assert!(validate("Title", "", "").is_err());
    }
}
