import re

INFO_FIELDS = 24
HEADER_FIELDS = 62
ITEM_FIELDS = 5

MONEY_RE = re.compile(r'^-?\d+(\.\d{1,4})?$')
DATE_RE = re.compile(r'^\d{8}(\d{6})?$')

class ValidationError(Exception):
    pass


def parse_section(lines, tag):
    if not lines or lines[0].strip() != tag:
        raise ValidationError(f'Missing section {tag}')
    if len(lines) < 2:
        raise ValidationError(f'No data for section {tag}')
    return lines[1]


def validate_epp(path):
    with open(path, 'r', encoding='cp1250') as f:
        content = [line.rstrip('\r\n') for line in f]

    if len(content) < 6:
        raise ValidationError('File too short')

    try:
        info_line = parse_section(content[0:2], '[INFO]')
        header_line = parse_section(content[2:4], '[NAGLOWEK]')
        # rest is ZAWARTOSC lines
        if content[4].strip() != '[ZAWARTOSC]':
            raise ValidationError('Missing section [ZAWARTOSC]')
        items = content[5:]
    except ValidationError as e:
        raise

    if info_line.count(',') + 1 != INFO_FIELDS:
        raise ValidationError('Incorrect number of INFO fields')
    if header_line.count(',') + 1 != HEADER_FIELDS:
        raise ValidationError('Incorrect number of NAGLOWEK fields')
    for line in items[:-1]:
        if line.count(',') + 1 != ITEM_FIELDS:
            raise ValidationError('Incorrect number of ZAWARTOSC fields')
        parts = line.split(',')
        for money in parts[1:]:
            if money and not MONEY_RE.match(money):
                raise ValidationError(f'Bad money value {money}')

    if items[-1] != '':
        raise ValidationError('File must end with blank line')

    return True
