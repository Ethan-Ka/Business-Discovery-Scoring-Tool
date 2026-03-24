with open('./sponsor_finder/ai_scoring.py', 'r') as f:
    lines = f.readlines()

# Find and update pull_model function
updated = False
for i, line in enumerate(lines):
    # Update function signature
    if 'def pull_model(name: str, on_progress, on_done, on_error):' in line:
        lines[i] = line.replace(
            'def pull_model(name: str, on_progress, on_done, on_error):',
            'def pull_model(name: str, on_progress, on_done, on_error, cancellation_token=None):'
        )
        updated = True
    
    # Update docstring to include cancellation_token
    if updated and '      on_error(message: str)' in line:
        lines[i] = line.replace(
            '      on_error(message: str)                          — called on failure',
            '      on_error(message: str)                          — called on failure\n      cancellation_token: CancellationToken to check for cancellation'
        )
        # Insert the extra parameter line
        if i+1 < len(lines) and lines[i+1].strip().startswith('"""'):
            pass  # docstring ends next
        updated = False  # Done with this part
    
    # Add cancellation check in the loop
    if 'for raw_line in r.iter_lines():' in line and 'download' not in ''.join(lines[max(0,i-5):i]):
        # Check if next line is the usual "if not raw_line:" check
        if i+1 < len(lines) and 'if not raw_line:' in lines[i+1]:
            # Insert cancellation check before the "if not raw_line" line
            indent = '                '
            new_lines = [
                indent + '# Check for cancellation during download\n',
                indent + "if cancellation_token and cancellation_token.is_cancelled():\n",
                indent + "    on_error('Download cancelled by user')\n",
                indent + "    return\n",
                '\n'
            ]
            lines = lines[:i+1] + new_lines + lines[i+1:]
            break

with open('./sponsor_finder/ai_scoring.py', 'w') as f:
    f.writelines(lines)

print('✓ Updated pull_model with cancellation support')
