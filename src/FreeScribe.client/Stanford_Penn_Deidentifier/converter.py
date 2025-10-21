import numpy as np

# Step 1: Read text file
def convert(output_npy_path, file=None, text=None):
    """
    Converts .txt to .npy (or if given text, will create .npy file for it)
    """
    if not file and not text:
        print("Expecting one of file or text to not be None")
        return

    if text:
        reports = [line.strip() for line in text.splitlines() if line.strip()]
    
    elif file:
        with open(file, "r", encoding="utf-8") as file:
            reports = [line.strip() for line in file if line.strip()]  # Read non-empty lines



    # Step 2: Save reports as .npy file
    #if not output_npy_path:
    #    output_npy_path = "C:\\OakridgeHeartClinic\\Stanford_Penn_Deidentifier\\reports.npy"  # Path to save the .npy file
    
    np.save(output_npy_path, np.array(reports))
    print(f"Reports saved to {output_npy_path}")

#convert("C:\\Users\\D10S2\\Dropbox\\Dx\\ECG\\OCR\\StanfordInput\\20241203165136takacs, mary ann, heart function clinic report dec 3 24.txt")