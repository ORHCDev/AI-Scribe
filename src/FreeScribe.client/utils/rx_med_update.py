"""
Fixed "Update Med List" (med_update) for the 0.1Rfx medication eForm.

Injected only into the copy of the form that AI Scribe opens after a consult upload
(see med_eform.prepare_med_form); the form template in Oscar is not changed, so forms opened by
hand keep the original function. The button's onclick="med_update();" looks the function up when
clicked, so overriding window.med_update is enough.

What the form's original med_update gets wrong (confirmed against the template in tests):
- it strips only the FIRST "Increase "/"Decrease "/"to " in the box, so with two changed meds the
  second stays as "Increase X to ..." and the old dose is kept;
- it does not know "Start " (the form's own "Start" checkbox adds it), so new meds are saved as
  "Start X ...";
- "Stop X" is added to the list as if it were a medication, and X stays;
- it strips only some LU codes, so "LU 497", "LU code 380", ... become separate "medications".

Behaviour here: each entry of the prescription body either
- "Stop X" / "Discontinue X" / "Hold X" / "D/C X": removes X from CURRENT MEDS;
- anything else (optionally "Start"/"Increase"/"Decrease ... to"): replaces the CURRENT MEDS entry
  for the same drug (first word, case-insensitive), or is added at the top if the drug is new.
CURRENT MEDS entries are written in the same "Drug dose frequency, " format; LU codes stay on the
prescription but are not copied into CURRENT MEDS. Multi-part standard lines such as the amiodarone
loading schedule are kept as one entry.
"""

MED_UPDATE_JS = r'''function med_update() {
    var LU_CODE = /^LU(\s+code)?\s*\d+$/i;
    var STOP = /^(stop|discontinue|d\/c|hold)\s+/i;
    var VERB = /^(start|starting|add|increase|decrease|reduce)\s+/i;

    // Pieces after a comma that continue the previous entry rather than start a new medication,
    // e.g. the form's own "Amiodarone 400 mg BID for 7 days, 200 mg TID for 3 days, ...",
    // "Zyban ..., THEN Increase to ..." and "0.4 mg P.R.N. nitroglycerin spray, SL for chest pain ...".
    var CONTINUATION = /^(then|sl|for|and|x|q|with|prn)\b/i;
    function continues(piece) {
        return CONTINUATION.test(piece) || (/^\d/.test(piece) && !/nitro/i.test(piece));
    }

    // Split a box into entries, dropping blanks and stand-alone LU codes.
    function entries(text) {
        var out = [];
        String(text || "").split(/[,\n]/).forEach(function (p) {
            p = p.trim();
            if (!p || LU_CODE.test(p)) { return; }
            if (out.length && continues(p)) { out[out.length - 1] += ", " + p; return; }
            out.push(p);
        });
        return out;
    }
    // "Increase Furosemide to 80 mg daily" -> "Furosemide 80 mg daily" (also for multi-word
    // names: "Increase Diltiazem CD to 240 mg daily" -> "Diltiazem CD 240 mg daily"); LU codes are for the
    // prescription only, so any left inside an entry are dropped from CURRENT MEDS too.
    function regimen(entry) {
        var e = entry.replace(VERB, "").replace(/\s+to\s+(?=[\d.])/i, " ");
        return e.replace(/,?\s*\bLU(\s+code)?\s*\d+\b/gi, "").replace(/\s+/g, " ").trim();
    }
    function drug(entry) {
        return regimen(entry).split(/\s+/)[0].toLowerCase();
    }

    var medsBox = document.getElementById("m$MEDS#value");
    var current = entries(medsBox.value).map(regimen);

    entries(document.getElementById("druglist_generic").value).forEach(function (entry) {
        var stopping = STOP.test(entry);
        var line = stopping ? entry.replace(STOP, "") : regimen(entry);
        var name = drug(line);
        if (!name) { return; }
        var index = -1;
        for (var i = 0; i < current.length; i++) {
            if (drug(current[i]) === name) { index = i; break; }
        }
        if (stopping) {
            if (index >= 0) { current.splice(index, 1); }
        } else if (index >= 0) {
            current[index] = line;
        } else {
            current.unshift(line);
        }
    });

    medsBox.value = current.map(function (m) { return m + ", "; }).join("");
}
'''
