import tkinter as tk

root = tk.Tk()
root.title("Entry Grid")

# Validation function
def validate_single_char(new_value):
    # Allow empty or single character only
    return len(new_value) <= 1

# Register the validation function
vcmd = (root.register(validate_single_char), '%P')

# Create a frame container
grid_frame = tk.Frame(root, bg="lightgray", bd=2, relief="groove")
grid_frame.pack(padx=10, pady=10)

rows = 4
cols = 5
entries = []

for i in range(rows):
    row_entries = []
    for j in range(cols):
        entry = tk.Entry(grid_frame, width=3, justify="center",
                        validate="key", validatecommand=vcmd)
        entry.grid(row=i, column=j, padx=2, pady=2)
        row_entries.append(entry)
    entries.append(row_entries)

root.mainloop()