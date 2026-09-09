"""Conservative prose language screening for the human cohort (sampler only)."""
import re


def prose(text):
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'https?://\S+|`[^`]*`|<[^>]*>|\[Image[^\]]*\]', ' ', text)
    return '\n'.join(line for line in text.splitlines() if len(re.findall(r'[{}=;|/\\]', line)) < 5)


def screen(events, quality):
    from langid.langid import LanguageIdentifier, model
    if not hasattr(screen, 'identifier'):
        screen.identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    turns = {p['turn'] for p in quality['prompts'] if p['reason'] is None}
    texts = [prose(e[3])[:2500] for e in sorted(events, key=lambda e:e[0]) if e[1] == 'user_prompt' and e[0] in turns]
    joined = '\n'.join(texts)[:25000]
    foreign_script = len(re.findall(r'[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff]', joined))
    language, confidence = screen.identifier.classify(joined)
    first_language, first_confidence = screen.identifier.classify(texts[0]) if texts else ('unknown',0)
    accepted = language in {'en', 'zh'} and foreign_script < 5 and not (first_confidence >= .9 and first_language not in {'en','zh'} and len(texts[0]) >= 80)
    return dict(accepted=accepted, language=language, confidence=float(confidence), first_prompt_language=first_language,
                method='langid 1.1.6 on substantive user prose, no restricted label set; first prompt and foreign script guard')
