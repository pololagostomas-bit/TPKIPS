"""Private rotation reference data; never changes receipts or inventory balances."""
from io import BytesIO
import re
from xml.etree.ElementTree import ParseError

from backend.services.safe_excel import load_workbook
from backend.services.sts_source import literal, normalized


def init_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS reception_rotation_catalog(
        item_key TEXT PRIMARY KEY,item_code TEXT NOT NULL,description TEXT NOT NULL,
        classification TEXT NOT NULL,source_file TEXT NOT NULL,loaded_at TEXT NOT NULL,
        loaded_by TEXT NOT NULL)''')


def parse_workbook(content):
    aliases={
        'np':{'NP','SKU','NP SKU','Código de artículo','Número de artículo','Código de artículo / NP'},
        'description':{'Descripción','Descripción del artículo','Descripción artículo/serv.'},
        'classification':{'Clasificación','Clasificación de rotación','Clasificación rotación','Rotación'},
    }
    try:
        book=load_workbook(BytesIO(content),read_only=True,data_only=True,keep_links=False)
    except (KeyError,ParseError,OSError) as error:
        raise ValueError('No se pudo leer el Excel de clasificación.') from error
    try:
        matches=[]
        for sheet in book.worksheets:
            for index,row in enumerate(sheet.iter_rows(max_row=20,max_col=30,values_only=True),1):
                columns={key:[i for i,value in enumerate(row) if normalized(value) in {normalized(name) for name in names}]
                    for key,names in aliases.items()}
                if all(columns.values()):
                    if any(len(found)!=1 for found in columns.values()):
                        raise ValueError('Conserva una sola columna de NP, descripción y clasificación.')
                    matches.append((sheet,index,{key:value[0] for key,value in columns.items()}));break
        if len(matches)!=1:
            raise ValueError('Usa una sola hoja con las columnas NP, Descripción y Clasificación.')
        sheet,header,columns=matches[0]
        items={};repeated=0
        for index,row in enumerate(sheet.iter_rows(min_row=header+1,max_col=30),header+1):
            if index-header>100000:
                raise ValueError('La clasificación admite hasta 100000 filas por carga.')
            if not any(cell.value is not None for cell in row):continue
            try:
                cell=row[columns['np']];value=cell.value
                if isinstance(value,(int,float)) and not isinstance(value,bool) and re.fullmatch('0+',cell.number_format) and value==int(value):
                    value=str(int(value)).zfill(len(cell.number_format))
                code=literal(value,'NP',100)
                classification=literal(row[columns['classification']].value,'Clasificación',60)
            except (ValueError,OverflowError) as error:
                raise ValueError(f'Fila {index}: {error}') from error
            key=code.upper()
            item={'item_code':code,'description':str(row[columns['description']].value or '').strip(),'classification':classification}
            if key in items:
                if items[key]['classification']!=classification:
                    raise ValueError(f'Fila {index}: el NP {code} tiene clasificaciones distintas. Revisa el Excel.')
                repeated+=1
            else:items[key]=item
        if not items:raise ValueError('El archivo no contiene clasificaciones. Se conservó el catálogo anterior.')
        return items,repeated
    except (KeyError,ParseError) as error:
        raise ValueError('No se pudo leer el Excel de clasificación.') from error
    finally:book.close()


def import_catalog(connection,parsed,identity):
    items,repeated=parsed
    connection.executemany('''INSERT INTO reception_rotation_catalog VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(item_key) DO UPDATE SET item_code=excluded.item_code,description=excluded.description,
        classification=excluded.classification,source_file=excluded.source_file,
        loaded_at=excluded.loaded_at,loaded_by=excluded.loaded_by''',
        [(key,item['item_code'],item['description'],item['classification'],identity['filename'],identity['loaded_at'],identity['username'])
         for key,item in items.items()])
    return {'classifications':len(items),'repeated_rows':repeated,'stock_updated':False}


def annotate(connection,lines):
    codes=list({str(line.get('np_code') or '').strip().upper() for line in lines})
    values={}
    for start in range(0,len(codes),900):
        chunk=codes[start:start+900]
        values.update(connection.execute('SELECT item_key,classification FROM reception_rotation_catalog WHERE item_key IN ('+','.join('?' for _ in chunk)+')',chunk).fetchall())
    for line in lines:line['rotation_classification']=values.get(str(line.get('np_code') or '').strip().upper(),'')
