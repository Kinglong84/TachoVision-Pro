"""
models/borders.py
=================
Paesi confinanti (o collegati da linee di traghetto) per il controllo del
simbolo del paese all'attraversamento di frontiera (Reg. UE 165/2014 Art. 34§7,
dal 02/02/2022): due luoghi consecutivi nello stesso turno in paesi non vicini
vuol dire che almeno un attraversamento non è stato registrato.
"""

# coppie (in ordine alfabetico) di paesi vicini
_NEIGHBOURS = {
    "AD": ['ES', 'FR'],
    "AL": ['GR', 'ME', 'MK', 'RS', 'YU'],
    "AM": ['AZ', 'GE', 'TR'],
    "AT": ['CH', 'CZ', 'DE', 'HU', 'IT', 'LI', 'SI', 'SK', 'YU'],
    "AZ": ['GE', 'RU', 'TR'],
    "BA": ['HR', 'ME', 'RS', 'YU'],
    "BE": ['DE', 'FR', 'GB', 'LU', 'NL'],
    "BG": ['GR', 'MK', 'RO', 'RS', 'TR', 'YU'],
    "BY": ['LT', 'LV', 'PL', 'RU', 'UA'],
    "CH": ['DE', 'FR', 'IT', 'LI'],
    "CY": ['TR'],
    "CZ": ['DE', 'PL', 'SK'],
    "DE": ['DK', 'FR', 'LU', 'NL', 'PL', 'SE'],
    "DK": ['IS', 'NO', 'SE'],
    "EE": ['FI', 'LV', 'RU', 'SE'],
    "ES": ['FR', 'PT'],
    "FI": ['NO', 'RU', 'SE'],
    "FR": ['GB', 'IT', 'LU', 'MC'],
    "GB": ['IE', 'NL'],
    "GE": ['RU', 'TR'],
    "GR": ['MK', 'TR', 'YU'],
    "HR": ['HU', 'ME', 'RS', 'SI', 'YU'],
    "HU": ['RO', 'RS', 'SI', 'SK', 'UA', 'YU'],
    "IT": ['MT', 'SI', 'SM', 'VA', 'YU'],
    "KZ": ['RU', 'TM', 'UZ'],
    "LT": ['LV', 'PL', 'RU', 'SE'],
    "LV": ['RU', 'SE'],
    "MD": ['RO', 'UA'],
    "ME": ['RS', 'YU'],
    "MK": ['RS', 'YU'],
    "NO": ['RU', 'SE'],
    "PL": ['RU', 'SE', 'SK', 'UA'],
    "RO": ['RS', 'UA', 'YU'],
    "RS": ['YU'],
    "RU": ['UA'],
    "SI": ['YU'],
    "SK": ['UA'],
    "TJ": ['UZ'],
    "TM": ['UZ'],
}

# paesi per cui il controllo non si applica (fuori dall'obbligo)
NOT_CHECKED = set(['AL', 'AM', 'AZ', 'BA', 'BY', 'EC', 'EUR', 'GE', 'MD', 'ME', 'MK', 'RS', 'RU', 'TR', 'UA', 'WLD'])


def neighbours(a: str, b: str) -> bool:
    """True se i due paesi sono uguali, confinanti o collegati via traghetto."""
    if a == b:
        return True
    x, y = sorted((a, b))
    return y in _NEIGHBOURS.get(x, ())
