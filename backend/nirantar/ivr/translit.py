"""Devanagari forms for the names, places and items used in outreach.

An automated voice call that says "Ganesh जी, अपने साथ लाएँ: health card"
sounds like a machine and gets hung up on. Since the generated world draws
names and villages from fixed lists, the Devanagari forms can simply be
provided rather than guessed at by a transliteration algorithm, which is
both better quality and fully auditable.

In a real deployment this table is replaced by the state health record's own
Devanagari name field, which already exists -- ABHA registration captures it.
Nothing here is clever; it is just the part most health-tech pilots skip, and
skipping it is why people stop answering the phone.
"""

from __future__ import annotations

NAMES: dict[str, str] = {
    # women
    "Sunita": "सुनीता", "Kamla": "कमला", "Rekha": "रेखा",
    "Phoolmati": "फूलमती", "Savitri": "सावित्री", "Anita": "अनीता",
    "Meena": "मीना", "Lalita": "ललिता", "Shanti": "शांति",
    "Gayatri": "गायत्री", "Rukmini": "रुक्मिणी", "Pushpa": "पुष्पा",
    "Saroj": "सरोज", "Urmila": "उर्मिला", "Chandrakala": "चंद्रकला",
    "Nirmala": "निर्मला", "Bhagwanti": "भगवंती", "Sarita": "सरिता",
    "Kaushalya": "कौशल्या", "Munni": "मुन्नी",
    # men
    "Ramesh": "रमेश", "Shivkumar": "शिवकुमार", "Dinesh": "दिनेश",
    "Mahendra": "महेंद्र", "Rajaram": "राजाराम", "Chhotelal": "छोटेलाल",
    "Virendra": "वीरेंद्र", "Ganesh": "गणेश", "Baijnath": "बैजनाथ",
    "Sohan": "सोहन", "Prem": "प्रेम", "Jagdish": "जगदीश",
    "Harish": "हरीश", "Mangal": "मंगल", "Devnarayan": "देवनारायण",
    "Suresh": "सुरेश", "Kallu": "कल्लू", "Raghunath": "रघुनाथ",
    "Ashok": "अशोक", "Bhola": "भोला",
    # surnames
    "Devi": "देवी", "Yadav": "यादव", "Kumar": "कुमार", "Prasad": "प्रसाद",
    "Ram": "राम", "Pal": "पाल", "Nishad": "निषाद", "Verma": "वर्मा",
    "Chaudhary": "चौधरी", "Sahni": "साहनी", "Paswan": "पासवान",
    "Bind": "बिंद", "Rajbhar": "राजभर", "Maurya": "मौर्य",
    "Kushwaha": "कुशवाहा",
}

PLACES: dict[str, str] = {
    "Amraulia": "अमरौलिया", "Bansgaon": "बांसगांव", "Chiraigaon": "चिरईगांव",
    "Dhanauli": "धनौली", "Etwa": "एतवा", "Gaurihar": "गौरिहार",
    "Haripur": "हरिपुर", "Jamunaha": "जमुनहा", "Kusmahi": "कुसमही",
    "Lakhanpur": "लखनपुर", "Mahuadanr": "महुआडांड़", "Nauranga": "नौरंगा",
    "Saryupar": "सरयूपार", "Bharatpur": "भरतपुर",
}

SUFFIXES: dict[str, str] = {
    "Khurd": "खुर्द", "Buzurg": "बुजुर्ग", "Tola": "टोला",
    "Bazar": "बाज़ार", "Pahar": "पहाड़", "Ghat": "घाट",
}

ITEMS: dict[str, str] = {
    "health card": "आयुष्मान या स्वास्थ्य कार्ड",
    "any medicines you take": "आप जो दवा लेते हैं",
    "empty medicine strip": "दवा का खाली पत्ता",
    "previous test slip": "पिछली जाँच की पर्ची",
    "test report": "जाँच की रिपोर्ट",
    "mother and child protection card": "माता-शिशु सुरक्षा कार्ड",
    "child immunisation card": "बच्चे का टीकाकरण कार्ड",
}

FACILITY_WORDS: dict[str, str] = {
    "Ayushman Arogya Mandir": "आयुष्मान आरोग्य मंदिर",
    "Primary Health Centre": "प्राथमिक स्वास्थ्य केंद्र",
    "Community Health Centre": "सामुदायिक स्वास्थ्य केंद्र",
    "District Hospital": "ज़िला अस्पताल",
}


def name(value: str) -> str:
    """Devanagari form of a person name, word by word."""
    return " ".join(NAMES.get(part, part) for part in value.split())


def place(value: str) -> str:
    """Devanagari form of a village or panchayat name, including suffixes."""
    parts = value.split()
    out = []
    for part in parts:
        if part in PLACES:
            out.append(PLACES[part])
        elif part in SUFFIXES:
            out.append(SUFFIXES[part])
        else:
            out.append(part)
    return " ".join(out)


def facility(value: str) -> str:
    """Devanagari form of a facility name like 'Primary Health Centre, X'."""
    for english, hindi in FACILITY_WORDS.items():
        if value.startswith(english):
            remainder = value[len(english) :].lstrip(", ").strip()
            return f"{place(remainder)} के {hindi}" if remainder else hindi
    return place(value)


def item(value: str) -> str:
    return ITEMS.get(value, value)
