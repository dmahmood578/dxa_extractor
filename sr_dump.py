import pydicom

def dump_sr(path):
    print("=" * 60)
    print(f"Dumping SR: {path}")
    print("=" * 60)
    try:
        ds = pydicom.dcmread(path)
        
        # A recursive function to format and print SR contents
        def print_sr_element(element, depth=0):
            indent = "  " * depth
            concept_name = ""
            if hasattr(element, 'ConceptNameCodeSequence'):
                seq = element.ConceptNameCodeSequence
                if len(seq) > 0:
                    concept_name = f"[{seq[0].CodeValue}] {seq[0].CodeMeaning}"
            
            value_str = ""
            if hasattr(element, 'TextValue'):
                value_str = f"TEXT: {element.TextValue}"
            elif hasattr(element, 'NumericValue'):
                val = element.NumericValue
                units = ""
                if hasattr(element, 'MeasurementUnitsCodeSequence'):
                    useq = element.MeasurementUnitsCodeSequence
                    if len(useq) > 0:
                        units = useq[0].CodeMeaning
                value_str = f"NUM: {val} {units}"
            elif hasattr(element, 'ConceptCodeSequence'):
                seq = element.ConceptCodeSequence
                if len(seq) > 0:
                    value_str = f"CODE: [{seq[0].CodeValue}] {seq[0].CodeMeaning}"
            elif hasattr(element, 'DateTime'):
                value_str = f"DATETIME: {element.DateTime}"
            elif hasattr(element, 'Date'):
                value_str = f"DATE: {element.Date}"
            elif hasattr(element, 'Time'):
                value_str = f"TIME: {element.Time}"
            elif hasattr(element, 'UIDValue'):
                value_str = f"UID: {element.UIDValue}"
                
            relationship = getattr(element, 'RelationshipType', '')
            if relationship:
                relationship = f"({relationship}) "
                
            print(f"{indent}{relationship}{element.ValueType}: {concept_name} = {value_str}")
            
            if hasattr(element, 'ContentSequence'):
                for child in element.ContentSequence:
                    print_sr_element(child, depth + 1)

        if hasattr(ds, 'ContentSequence'):
            # The root element doesn't have a value type in ContentSequence, it is the root of the document
            print(f"Document Title: {getattr(ds, 'ConceptNameCodeSequence', [None])[0].CodeMeaning if getattr(ds, 'ConceptNameCodeSequence', None) else 'N/A'}")
            for item in ds.ContentSequence:
                print_sr_element(item, depth=0)
        else:
            print("No ContentSequence in this dataset.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()

dump_sr("CLD DXA/1/DICOM/000061C8/AA9059FF/AA9D2FAE/0000F512/FFCAAB8E")
