"""Keep untrusted bibliographic and model strings literal in spreadsheet exports."""


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def csv_row(row):
    return {key: csv_cell(value) for key, value in row.items()}


def literal_workbook(workbook):
    for worksheet in workbook:
        for row in worksheet:
            for cell in row:
                if cell.data_type == 'f':
                    cell.data_type = 's'
