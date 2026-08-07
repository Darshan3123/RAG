# Install the required dependency first by running:
# pip install pypandoc_binary

import pypandoc
from pathlib import Path

input_file = 'ATC_4dd85a2a-9be5-4378-804f1777709456453_PCMM_02 (6).docx'

# Automatically use the exact same name as the input file, just changing the extension to .md
output_file = Path(input_file).with_suffix('.md')

# Convert the file and save the output
pypandoc.convert_file(input_file, 'gfm', outputfile=str(output_file))

print(f"Conversion complete! Saved as {output_file}")