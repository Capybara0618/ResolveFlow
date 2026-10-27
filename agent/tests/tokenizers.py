"""Small deterministic tokenizer for policy segmentation tests."""

class CharacterTokenizer:
    def __call__(self, text, *, truncation=False, add_special_tokens=True, return_offsets_mapping=False):
        assert truncation is False and add_special_tokens is True
        output = {"input_ids": [0] + [ord(c) for c in text] + [1]}
        if return_offsets_mapping:
            output["offset_mapping"] = [(0, 0)] + [(i, i + 1) for i in range(len(text))] + [(0, 0)]
        return output
