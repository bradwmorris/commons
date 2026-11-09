# Embedding tokenizer

`embeddinggemma2-tokenizer.json` is Google's original EmbeddingGemma 2 tokenizer,
downloaded unchanged from revision c9b793c3358600b31f2cf5dacbd96ad2c26e904a:
https://huggingface.co/google/embeddinggemma-2/blob/c9b793c3358600b31f2cf5dacbd96ad2c26e904a/tokenizer.json

SHA-256: `4d777ef5bdc1aa36227abdfb77c3e49e7b9c892d16e1b6bda41c393504828be4`.
The upstream model repository identifies its license as Apache-2.0. Retain this
attribution and the repository's Apache-2.0 license. No model weights or private
data are included. `packet.rs` verifies the hash and uses the tokenizer locally;
counting does not invoke Ollama or a generative model. Changes to the pinned model
or tokenizer require an explicit embedding-input version change and rebuild.
