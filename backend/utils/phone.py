"""Phone normalisation to E.164 (spec §11). Canada + US share country code +1
(NANP). Other countries are accepted only if listed in otp.allowed_countries."""
import re

# NANP premium-rate / personal / non-geographic area codes that must never receive OTPs
# (SMS-pumping / toll-fraud targets — spec §11.2 #10).
PREMIUM_NANP = ('500', '533', '544', '566', '577', '588', '700', '710', '900', '976')
# +1 area codes that are NOT Canada or the US mainland (Caribbean, Atlantic and
# Pacific territories). They share +1 but are billed internationally and are the
# classic SMS-pumping targets, so they are refused unless the region is listed in
# otp.allowed_countries (ISO code) or otp.allowed_nanp_regions (area code / ISO).
NANP_OTHER = {
    '242': 'BS', '246': 'BB', '264': 'AI', '268': 'AG', '284': 'VG', '340': 'VI', '345': 'KY', '441': 'BM',
    '473': 'GD', '649': 'TC', '658': 'JM', '664': 'MS', '670': 'MP', '671': 'GU', '684': 'AS', '721': 'SX',
    '758': 'LC', '767': 'DM', '784': 'VC', '787': 'PR', '809': 'DO', '829': 'DO', '849': 'DO', '868': 'TT',
    '869': 'KN', '876': 'JM', '939': 'PR',
}
COUNTRY_PREFIX = {'CA': '+1', 'US': '+1', 'UG': '+256', 'NG': '+234', 'GB': '+44'}


class PhoneError(ValueError):
    pass


def normalize(raw, default_country='CA'):
    """'(416) 555-0199' → '+14165550199'. Raises PhoneError."""
    if raw is None:
        raise PhoneError('Phone number is required.')
    s = str(raw).strip()
    plus = s.startswith('+')
    digits = re.sub(r'\D', '', s)
    if s.startswith('00'):
        digits, plus = digits[2:], True
    if not digits:
        raise PhoneError('Phone number is required.')
    if plus:
        e164 = '+' + digits
    elif len(digits) == 10 and COUNTRY_PREFIX.get(default_country) == '+1':
        e164 = '+1' + digits
    elif len(digits) == 11 and digits.startswith('1'):
        e164 = '+' + digits
    else:
        e164 = COUNTRY_PREFIX.get(default_country, '+1') + digits.lstrip('0')
    if not re.fullmatch(r'\+[1-9]\d{7,14}', e164):
        raise PhoneError('That phone number does not look valid.')
    if e164.startswith('+1'):
        if len(e164) != 12:
            raise PhoneError('Canadian and US numbers have 10 digits.')
        area, exchange = e164[2:5], e164[5:8]
        if area[0] in '01' or exchange[0] in '01':
            raise PhoneError('That phone number does not look valid.')
    return e164


def country_of(e164):
    if e164.startswith('+1'):
        return NANP_OTHER.get(e164[2:5], 'CA')  # NANP: CA/US unless a Caribbean/territory area code
    for c, p in COUNTRY_PREFIX.items():
        if e164.startswith(p):
            return c
    return None


def is_premium(e164):
    return e164.startswith('+1') and e164[2:5] in PREMIUM_NANP


def is_allowed_country(e164, allowed_csv='CA,US', extra_nanp_csv=''):
    allowed = {c.strip().upper() for c in (allowed_csv or '').split(',') if c.strip()}
    if e164.startswith('+1'):
        area = e164[2:5]
        if area in NANP_OTHER:
            extra = {c.strip().upper() for c in (extra_nanp_csv or '').split(',') if c.strip()}
            return area in extra or NANP_OTHER[area] in extra or NANP_OTHER[area] in allowed
        return bool(allowed & {'CA', 'US'})
    c = country_of(e164)
    return c in allowed if c else False


def safe_normalize(raw, default_country='CA'):
    try:
        return normalize(raw, default_country)
    except PhoneError:
        return None


def mask(e164):
    if not e164 or len(e164) < 6:
        return e164
    return e164[:-4].replace(e164[2:-4], '•' * len(e164[2:-4])) + e164[-4:]
