from Stanford_Penn_Deidentifier import converter, read
import subprocess


def stanford_deidentify(text):
    """
    Removes possible identifying features from the text, like patient name, doctor names, dates, addresses, etc.
    Uses the Stanford_Penn_Deidentifier from https://github.com/MIDRC/Stanford_Penn_Deidentifier.git
    """

    # Can change these paths as needed
    script_path = "./Stanford_Penn_Deidentifier/main.py"
    input_path = "./Stanford_Penn_Deidentifier/reports.npy"
    output_path = "./Stanford_Penn_Deidentifier/reports_stanford_deidentified.npy"
    python_exe = "./Stanford_Penn_Deidentifier/stanford_venv/scripts/python.exe"
    device = "cpu" #"cuda:0"

    # Convert to .npy file
    converter.convert(input_path, text=text)

    # Run deidentify process
    args = [
        python_exe,
        script_path,
        "--input_file_path", input_path,  # Input file argument
        "--output_file_path", output_path,  # Output file argument
        "--device_list", device,
    ]
    try:
        result = subprocess.run(args, check=True, text=True, capture_output=True)
        print("Script executed successfully!")
        print("Output:\n", result.stdout)
    except subprocess.CalledProcessError as e:
        print("Error occurred while running the script!")
        print("Error:\n", e.stderr)

    # Read text results
    redacted_text = read.read(output_path)

    """with open("./temp_file.txt", "w") as f:
        f.write(redacted_text)"""

    return redacted_text