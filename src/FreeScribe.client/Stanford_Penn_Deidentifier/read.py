import numpy as np

def read(file_path):
    #if not file_path:
    #    file_path = "C:\\OakridgeHeartClinic\\Stanford_Penn_Deidentifier\\reports_stanford_deidentified.npy"  
    deidentified_reports = np.load(file_path, allow_pickle=True)

    # Print the loaded data (deidentified reports)
    result = ""
    for idx, report in enumerate(deidentified_reports, start=1):
        result += f"{report}\n"
      

    
    return result

    
#read()

