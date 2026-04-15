import re
import nltk

class Chunker:

    def __init__(self):
        self.medical_terms = {
            "ventricle", "ventricular", "systolic", "diastolic",
            "ischemia", "coronary", "artery", "echo", "cardiac",
            "sinus", "rhythm", "valve", "atrial", "left", "right",
            "heart", "rate", "blood", "pressure", "stress", "normal",
            "arrhythmia", "inducible", "achieved", "workload", "fatigue",
            "beta", "blockade", "capacity", "physician", "technician",
            "exercise", "rest", "test", "result", "findings", "impression",
            "patient", "history", "medication", "dose", "mg", "bpm",
            "ejection", "fraction", "wall", "motion", "stenosis", "regurgitation",
            "mitral", "aortic", "tricuspid", "pulmonic", "septal", "anterior",
            "posterior", "inferior", "lateral", "hypertension", "fibrillation",
            "tachycardia", "bradycardia", "murmur", "pericardium", "myocardium",
            "perfusion", "imaging", "nuclear", "catheterization", "angiography",
            "stent", "bypass", "graft", "occlusion", "thrombosis", "embolism",
            "edema", "dyspnea", "palpitation", "syncope", "angina", "infarction",
            "congestive", "failure", "chronic", "acute", "mild", "moderate",
            "severe", "borderline", "within", "limits", "noted", "observed",
            "demonstrated", "evidence", "conclusion", "report", "date", "name",
            "age", "sex", "male", "female", "stage", "recovery", "pretest",
            "supine", "peak", "target", "achieved", "protocol", "speed",
            "grade", "mets", "duration", "elapsed",
        }

        # Time values like 01:03, 14:22
        self._RE_TIME        = re.compile(r"\b\d{1,2}:\d{2}\b")
        # Blood pressure like 136/77, 152/80
        self._RE_BP          = re.compile(r"\b\d{2,3}/\d{2,3}\b")
        # Decimal measurements like 1.70, 3.40 (METs, speed, grade)
        self._RE_DECIMAL     = re.compile(r"\b\d+\.\d+\b")
        # Standalone integers that look like HR/BPM values (50–250)
        self._RE_HR          = re.compile(r"\b(5[0-9]|[6-9]\d|1\d{2}|2[0-4]\d)\b")
        # Stage/phase labels
        self._RE_STAGE       = re.compile(
            r"\b(stage\s*\d+|pretest|recovery|exercise|rest|supine|peak|baseline)\b",
            re.IGNORECASE
        )
        # Key:value style entries like "HR: 95" or "BP 136/77"
        self._RE_KV_MEDICAL  = re.compile(
            r"\b(hr|bp|bpm|mets?|mph|spd|grade|dur|min|sec|vo2)\b",
            re.IGNORECASE
        )

        nltk.download("punkt")
        nltk.download("punkt_tab")



    def _is_structured_medical_data(self, stripped: str) -> bool:
        """
        Returns True if the line looks like a structured numeric medical record
        row (stress test table, vitals log, measurement series, etc.).

        Strategy: require at least 2 independent numeric/clinical signals.
        A single number could be a page number or OCR artifact; two or more
        distinct signal types strongly indicate a real data row.
        """
        signals = 0

        if self._RE_TIME.search(stripped):
            signals += 1
        if self._RE_BP.search(stripped):
            signals += 1
        if self._RE_DECIMAL.search(stripped):
            signals += 1
        if self._RE_HR.search(stripped):
            signals += 1
        if self._RE_STAGE.search(stripped):
            signals += 2  # stage/phase label is a strong anchor on its own
        if self._RE_KV_MEDICAL.search(stripped):
            signals += 1

        return signals >= 2




    def _line_score(self, line: str) -> float:
        """
        Score a single line. Returns a float in [0, 1].
        Lines scoring below a threshold are considered junk.
        """
        stripped = line.strip()
        if not stripped:
            return 0.0
        
        # Numeric rows like stress-test tables must bypass the word-ratio gates
        # because they're intentionally low on prose words.
        if self._is_structured_medical_data(stripped):
            return 0.75   


        # --- Hard disqualifiers ---

        # Very short lines (likely stray chars/labels)
        if len(stripped) <= 3:
            return 0.0

        chars = list(stripped)
        total = len(chars)

        alpha_chars = sum(c.isalpha() for c in chars)
        digit_chars = sum(c.isdigit() for c in chars)
        space_chars = sum(c == ' ' for c in chars)
        special_chars = total - alpha_chars - digit_chars - space_chars

        alpha_ratio    = alpha_chars / total
        special_ratio  = special_chars / total
        space_ratio    = space_chars / total

        # Lines dominated by special/symbol characters are OCR artifacts
        if special_ratio > 0.35:
            return 0.0

        words = re.findall(r"[A-Za-z]+", stripped.lower())
        num_words = len(words)

        # No real words at all
        if num_words == 0:
            return 0.0

        avg_word_len = sum(len(w) for w in words) / num_words

        # Single-character "words" dominate → OCR noise (e.g. "E a", "Z :")
        single_char_words = sum(1 for w in words if len(w) == 1)
        single_char_ratio = single_char_words / num_words
        if single_char_ratio > 0.5:
            return 0.0

        # Fragmented lines: lots of 1–2 char tokens separated by spaces
        tokens = stripped.split()
        short_tokens = sum(1 for t in tokens if len(t) <= 2)
        short_token_ratio = short_tokens / len(tokens) if tokens else 1.0

        # --- Soft scoring features ---

        # 1. Alpha content ratio (want high)
        f_alpha = alpha_ratio  # [0,1]

        # 2. Word count (want enough words for a real sentence fragment)
        f_words = min(num_words / 8, 1.0)

        # 3. Average word length (real prose words tend to be 4–8 chars)
        f_word_len = min(avg_word_len / 6, 1.0)

        # 4. Medical/domain term hits
        medical_hits = sum(1 for w in words if w in self.medical_terms)
        f_medical = min(medical_hits / 3, 1.0)

        # 5. Penalise high special-char ratio
        f_special_penalty = 1.0 - min(special_ratio / 0.2, 1.0)

        # 6. Penalise fragmented short-token lines
        f_frag_penalty = 1.0 - min(short_token_ratio / 0.5, 1.0)

        # 7. Reward lines that look like a sentence (end with punctuation or are long)
        has_sentence_end = bool(re.search(r"[.!?]$", stripped))
        f_sentence = 0.15 if has_sentence_end else 0.0

        score = (
            f_alpha          * 0.25 +
            f_words          * 0.15 +
            f_word_len       * 0.15 +
            f_medical        * 0.20 +
            f_special_penalty* 0.10 +
            f_frag_penalty   * 0.10 +
            f_sentence       * 0.05
        )

        return round(score, 4)



    
    def _filter_ocr_lines(
        self,
        text: str,
        threshold: float = 0.18,
        junk_between: int = 2,

        
    ) -> tuple[str, list[dict]]:
        """
        Filter junk lines from OCR text.

        Args:
            text: Raw OCR text (newline-separated).
            threshold: Lines scoring below this are junk. Default 0.18.
            min_consecutive_junk: Once this many junk lines appear in a row,
                suppress the whole run (avoids keeping stray good-looking
                lines inside a junk block).

        Returns:
            (clean_text, diagnostics)  where diagnostics is a list of
            {line, score, kept} dicts for inspection.
        """
        lines = text.splitlines()
        scored = [(ln, self._line_score(ln)) for ln in lines]

        # Two-pass: mark individual junk, then widen runs
        kept_flags = [score >= threshold for _, score in scored]

        # Suppress isolated "good" lines sandwiched in junk blocks
        n = len(kept_flags)
        for i in range(1, n - 1):
            if kept_flags[i] and not kept_flags[i - 1] and not kept_flags[i + 1]:
                # single good line surrounded by junk — likely a stray label
                _, sc = scored[i]
                if sc < threshold + 0.10:   # only suppress if only marginally good
                    kept_flags[i] = False

        # Keep isolated "junk" lines sandwiched between good blocks
        # I.e. may have test result numbers on line below header
        for i in range(junk_between, n-junk_between):
            above = any([kf for kf in kept_flags[i+1:junk_between+1]])
            below = any([kf for kf in kept_flags[i-junk_between:i]])
            if above and below:
                # single junk line surround by good - likely test value blurb
                kept_flags[i] = True
                

        clean_lines = [ln for ln, flag in zip(lines, kept_flags) if flag]
        diagnostics = [
            {"line": ln, "score": sc, "kept": flag}
            for (ln, sc), flag in zip(scored, kept_flags)
        ]

        return "\n".join(clean_lines), diagnostics



    def chunk_score(self, text: str) -> float:
        """
        Score a multi-line chunk by averaging per-line scores,
        ignoring empty lines.
        """
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return {
                "avg" : 0.0,
                "max" : 0.0
            }
        scores = [self._line_score(ln) for ln in lines]
        return {
            "avg" : round(sum(scores) / len(lines), 4),
            "max" : max(scores)
        }


    def chunk_medical_document(self, text : str, max_len : int=1200, threshold : float=22):
        """
        Given text from a medical document, will create chunks.
        """

        sentences = nltk.sent_tokenize(text)

        chunks = []
        chunk = ""

        for s in sentences:
            if len(chunk) + len(s) < max_len:
                chunk += " " + s
            else:
                chunks.append(chunk.strip())
                chunk =  s
        chunks.append(chunk.strip())

        kept_chunks = []
        for c in chunks:
            if self.chunk_score(c)["avg"] < threshold:
                kept_chunks.append(c)
            
        return kept_chunks