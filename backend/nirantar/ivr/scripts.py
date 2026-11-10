"""Outreach artefacts: the actual words a patient hears or reads.

Three hard constraints shaped this module.

**Voice first.** Roughly a quarter of the adults in the generated block
cannot read. An SMS to them is not communication, it is a compliance
artefact. The default channel is therefore an automated voice call in the
patient's own language, and text is the exception rather than the default.

**Never state a diagnosis on an unverified channel.** A call can be answered
by a neighbour, and in much of rural India the handset belongs to a husband
or son rather than to the woman being called. So the script says a health
worker needs to meet you about your check-up; it does not announce that you
may have tuberculosis. This is a deliberate clinical-privacy decision, not
an oversight, and it is enforced in code rather than left to the prompt.

**Every script ships with an English gloss.** A block medical officer
reviewing outreach, or a hackathon judge who does not read Bhojpuri, must be
able to see exactly what was said. Nothing goes out that a supervisor cannot
read back.

Machine-generated vernacular is marked ``requires_native_review`` until a
native speaker signs it off. Shipping unreviewed health messaging in
somebody's mother tongue is how you destroy trust in a programme, so the
flag is surfaced in the API and the dashboard rather than buried.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import translit

# What we are willing to say out loud about why we are calling. Reassuring,
# accurate, and non-diagnostic.
REASON_PHRASE: dict[str, dict[str, str]] = {
    "hypertension_suspect": {
        "en": "your blood pressure reading needs to be checked once more",
        "hi": "आपके रक्तचाप की जाँच एक बार फिर करनी है",
        "bho": "रउरा खून के दबाव के जाँच एक बेर फेरु करे के बा",
    },
    "hypertension_refill_due": {
        "en": "your blood pressure medicine is due",
        "hi": "आपकी रक्तचाप की दवा लेने का समय हो गया है",
        "bho": "रउरा खून के दबाव के दवाई लेबे के समय आ गइल बा",
    },
    "diabetes_suspect": {
        "en": "your sugar reading needs to be checked once more",
        "hi": "आपकी शुगर की जाँच एक बार फिर करनी है",
        "bho": "रउरा सुगर के जाँच एक बेर फेरु करे के बा",
    },
    "diabetes_refill_due": {
        "en": "your sugar medicine is due",
        "hi": "आपकी शुगर की दवा लेने का समय हो गया है",
        "bho": "रउरा सुगर के दवाई लेबे के समय आ गइल बा",
    },
    "tb_pulmonary_suspect": {
        "en": "a follow-up test for your cough is pending",
        "hi": "आपकी खाँसी की एक जाँच बाकी है",
        "bho": "रउरा खाँसी के एक जाँच बाकी बा",
    },
    "tb_confirmed_not_initiated": {
        "en": "your treatment needs to be started without delay",
        "hi": "आपका इलाज बिना देरी शुरू करना ज़रूरी है",
        "bho": "रउरा इलाज बिना देरी शुरू करे के जरूरी बा",
    },
    "anaemia_pregnancy_severe": {
        "en": "your blood test during pregnancy needs urgent attention",
        "hi": "गर्भावस्था में आपके खून की जाँच पर तुरंत ध्यान देना ज़रूरी है",
        "bho": "गरभ के समय रउरा खून के जाँच प तुरंते धेयान देबे के जरूरी बा",
    },
    "anaemia_pregnancy_moderate": {
        "en": "your iron tablets are due",
        "hi": "आपकी आयरन की गोलियाँ लेने का समय हो गया है",
        "bho": "रउरा लोहा के गोली लेबे के समय आ गइल बा",
    },
    "anc_visit_overdue": {
        "en": "your pregnancy check-up is due",
        "hi": "आपकी गर्भावस्था की जाँच का समय हो गया है",
        "bho": "रउरा गरभ के जाँच के समय आ गइल बा",
    },
    "oral_cancer_suspect": {
        "en": "the sore in your mouth needs to be examined by a doctor",
        "hi": "आपके मुँह के घाव को डॉक्टर से दिखाना ज़रूरी है",
        "bho": "रउरा मुँह के घाव डाक्टर के देखावे के जरूरी बा",
    },
    "cervical_cancer_suspect": {
        "en": "your screening test needs a follow-up examination",
        "hi": "आपकी जाँच के बाद एक और परीक्षण ज़रूरी है",
        "bho": "रउरा जाँच के बाद एगो और परीछन जरूरी बा",
    },
    "breast_lump_suspect": {
        "en": "you need an examination by a doctor",
        "hi": "आपको डॉक्टर से जाँच करानी है",
        "bho": "रउरा के डाक्टर से जाँच करावे के बा",
    },
    "immunisation_overdue": {
        "en": "your child's vaccination is due",
        "hi": "आपके बच्चे का टीका लगने का समय हो गया है",
        "bho": "रउरा बचवा के टीका लगे के समय आ गइल बा",
    },
    "child_sam_suspect": {
        "en": "your child's weight needs urgent attention from a doctor",
        "hi": "आपके बच्चे के वज़न पर डॉक्टर का तुरंत ध्यान ज़रूरी है",
        "bho": "रउरा बचवा के वजन प डाक्टर के तुरंते धेयान जरूरी बा",
    },
}

MONTHS_HI = [
    "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
    "जुलाई", "अगस्त", "सितंबर", "अक्तूबर", "नवंबर", "दिसंबर",
]

# Which languages we have hand-written copy for. Everything else falls back
# to Hindi and is flagged, rather than silently machine-translated.
SUPPORTED = {"Hindi": "hi", "Bhojpuri": "bho"}


def _date_phrase(when: date, lang_code: str) -> str:
    if lang_code in {"hi", "bho"}:
        return f"{when.day} {MONTHS_HI[when.month - 1]}"
    return when.strftime("%d %B")


def build_voice_script(
    *,
    person_name: str,
    condition: str,
    where: str,
    when: date | None,
    asha_name: str | None,
    language: str,
    zero_travel: bool,
    bring_items: list[str],
) -> dict[str, Any]:
    """Compose an IVR script plus an English gloss and delivery metadata."""
    lang_code = SUPPORTED.get(language, "hi")
    fell_back = language not in SUPPORTED
    reason = REASON_PHRASE.get(
        condition, REASON_PHRASE["hypertension_suspect"]
    )
    # Address respectfully; never use the diagnosis as a greeting.
    first_name = person_name.split()[0]
    when_phrase = _date_phrase(when, lang_code) if when else ""
    # Devanagari forms, so the call does not switch scripts mid-sentence.
    first_name_dev = translit.name(first_name)
    where_dev = translit.facility(where)
    asha_name_dev = translit.name(asha_name) if asha_name else None
    bring_dev = [translit.item(entry) for entry in bring_items]

    if lang_code == "bho":
        lines = [
            "नमस्कार। हम सरकारी स्वास्थ्य केंद्र से बोल रहल बानी।",
            f"{first_name_dev} जी खातिर एगो संदेश बा।",
            f"रउरा पिछला जाँच के बारे में — {reason['bho']}।",
        ]
        if zero_travel:
            lines.append(
                f"{when_phrase} के दिन स्वास्थ्य टीम रउरा गाँवे आ रहल बा। "
                f"रउरा के कहीं जाए के जरूरत नइखे।"
            )
        else:
            lines.append(f"{when_phrase} के दिन {where_dev} में रउरा खातिर समय रखल गइल बा।")
        if asha_name_dev:
            lines.append(f"आशा बहिन {asha_name_dev} रउरा साथे रहिहें।")
        if bring_dev:
            lines.append("अपना साथे ले आईं: " + ", ".join(bring_dev) + "।")
        lines.append("आवे खातिर एक दबाईं। बाद में बात करे खातिर दू दबाईं।")
        lines.append("ई सेवा मुफ्त बा। धन्यवाद।")
    else:
        lines = [
            "नमस्ते। मैं सरकारी स्वास्थ्य केंद्र से बोल रही हूँ।",
            f"{first_name_dev} जी के लिए एक संदेश है।",
            f"आपकी पिछली जाँच के बारे में — {reason['hi']}।",
        ]
        if zero_travel:
            lines.append(
                f"{when_phrase} को स्वास्थ्य टीम आपके गाँव आ रही है। "
                f"आपको कहीं जाने की ज़रूरत नहीं है।"
            )
        else:
            lines.append(f"{when_phrase} को {where_dev} में आपके लिए समय रखा गया है।")
        if asha_name_dev:
            lines.append(f"आशा बहन {asha_name_dev} आपके साथ रहेंगी।")
        if bring_dev:
            lines.append("अपने साथ लाएँ: " + ", ".join(bring_dev) + "।")
        lines.append("आने के लिए एक दबाएँ। बाद में बात करने के लिए दो दबाएँ।")
        lines.append("यह सेवा निःशुल्क है। धन्यवाद।")

    gloss = [
        "Hello. I am calling from the government health centre.",
        f"This is a message for {first_name}.",
        f"Regarding your last check-up — {reason['en']}.",
    ]
    if zero_travel:
        gloss.append(
            f"On {when.strftime('%d %B') if when else 'the scheduled day'} the health "
            f"team is coming to your village. You do not need to travel anywhere."
        )
    else:
        gloss.append(
            f"On {when.strftime('%d %B') if when else 'the scheduled day'} a slot has "
            f"been held for you at {where}."
        )
    if asha_name:
        gloss.append(f"ASHA {asha_name} will be with you.")
    if bring_items:
        gloss.append("Please bring: " + ", ".join(bring_items) + ".")
    gloss.append("Press 1 to confirm. Press 2 to be called back later.")
    gloss.append("This service is free of charge. Thank you.")

    script = "\n".join(lines)
    return {
        "language": language,
        "language_code": lang_code,
        "fell_back_to_hindi": fell_back,
        "requires_native_review": True,
        "script": script,
        "english_gloss": "\n".join(gloss),
        "estimated_duration_seconds": max(18, int(len(script.split()) / 2.1)),
        "dtmf": {"1": "confirm attendance", "2": "request callback"},
        "privacy_note": (
            "The script never names the diagnosis. Handsets in this setting "
            "are frequently shared, so the call states only that a check-up "
            "follow-up is pending."
        ),
        "retry_policy": {
            "attempts": 3,
            "spacing_hours": [0, 6, 30],
            "time_window_local": "09:00-19:00",
            "note": (
                "Calls outside daylight hours are not placed. A third failed "
                "attempt converts the task to an ASHA home visit rather than "
                "a fourth call."
            ),
        },
    }


def build_whatsapp_message(
    *,
    person_name: str,
    condition: str,
    where: str,
    when: date | None,
    asha_name: str | None,
    language: str,
    zero_travel: bool,
) -> dict[str, Any]:
    lang_code = SUPPORTED.get(language, "hi")
    reason = REASON_PHRASE.get(condition, REASON_PHRASE["hypertension_suspect"])
    first_name = person_name.split()[0]
    when_phrase = _date_phrase(when, lang_code) if when else ""
    where_dev = translit.facility(where)
    place = f"आपके गाँव में — {where_dev}" if zero_travel else where_dev
    body = (
        f"नमस्ते {translit.name(first_name)} जी,\n"
        f"{reason['hi']}।\n"
        f"📅 {when_phrase}\n"
        f"📍 {place}\n"
        + (
            f"👩 आशा बहन {translit.name(asha_name)} साथ रहेंगी\n"
            if asha_name
            else ""
        )
        + "💰 निःशुल्क\n\n"
        "आने के लिए 'हाँ' भेजें।"
    )
    return {
        "language": language,
        "body": body,
        "english_gloss": (
            f"Hello {first_name}, {reason['en']}. "
            f"{when.strftime('%d %B') if when else ''} at {place}. "
            + (f"ASHA {asha_name} will accompany you. " if asha_name else "")
            + "Free of charge. Reply 'yes' to confirm."
        ),
        "requires_native_review": True,
    }


def build_sms_fallback(*, when: date | None, where: str, zero_travel: bool) -> dict[str, Any]:
    """160-character fallback, used only when voice has failed repeatedly."""
    when_phrase = when.strftime("%d/%m") if when else "soon"
    text = (
        f"Swasthya jaanch: {when_phrase}, "
        + ("aapke gaon mein" if zero_travel else where)
        + ". Nishulk. Vivaran ke liye is number par call karein."
    )
    return {
        "body": text[:160],
        "transliterated": True,
        "note": (
            "Roman transliteration rather than Devanagari: many feature "
            "phones in this setting render Devanagari SMS as boxes."
        ),
    }


def build_asha_task_card(
    *,
    person: Any,
    debt: Any,
    plan_label: str,
    when: date | None,
    where: str,
    accompany: bool,
    bring_items: list[str],
    risk_score: float,
    binding_constraint: str,
) -> dict[str, Any]:
    """A task card an ASHA can act on from a feature phone or on paper.

    Kept to one screen. An ASHA has eighty of these a month and is paid per
    task; a card she has to scroll is a card she does not read.
    """
    return {
        "headline": f"{person.display_name}, {person.age}{'F' if person.sex == 'female' else 'M'} — {person.village}",
        "what": plan_label,
        "when": when.isoformat() if when else "to be scheduled",
        "where": where,
        "accompany_patient": accompany,
        "bring": bring_items,
        "priority": "high" if risk_score >= 60 else "normal",
        "main_obstacle": binding_constraint,
        "say_this": (
            "Explain that the check-up is free, that it is close by, and that "
            "you will be there. Do not discuss the diagnosis in front of "
            "others."
        ),
        "mark_done_requires": (
            "Record the measurement or the medicine handed over. The task "
            "cannot be closed without it."
        ),
        "payload_bytes_estimate": 420,
        "offline_capable": True,
    }
