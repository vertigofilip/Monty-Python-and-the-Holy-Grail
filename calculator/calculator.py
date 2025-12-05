import tkinter as tk

class SimplePaintApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calculator")
        
        # Variables to hold calculation logic
        self.current_input = ""  # Stores the string being typed
        self.total = 0           # Stores the result
        
        # 1. FIX: Separate widget creation from packing
        self.serial_text = tk.Label(root, text="0", font=("Courier", 24), anchor='e', bg="white")
        self.serial_text.pack(fill=tk.X, padx=10, pady=10)

        # 2. FIX: Typo was "Flame", changed to "Frame"
        controls = tk.Frame(root)
        controls.pack(fill=tk.BOTH, expand=True)

        # Define buttons in a list of rows for a grid layout
        buttons = [
            ['7', '8', '9', '/'],
            ['4', '5', '6', '*'],
            ['1', '2', '3', '-'],
            ['.', '0', 'AC', '+'],
            ['='] # Added an equals button
        ]

        # Loop to create buttons automatically
        for r, row in enumerate(buttons):
            for c, char in enumerate(row):
                # 3. FIX: Use lambda to prevent command from running immediately
                btn = tk.Button(controls, text=char, font=("Arial", 18),
                                command=lambda x=char: self.on_button_click(x))
                
                # Stretch the equals button across the bottom
                if char == '=':
                    btn.grid(row=r, column=0, columnspan=4, sticky="nsew")
                else:
                    btn.grid(row=r, column=c, sticky="nsew")

        # Configure grid weights so buttons expand nicely
        for i in range(4):
            controls.grid_columnconfigure(i, weight=1)
        for i in range(5):
            controls.grid_rowconfigure(i, weight=1)

    def on_button_click(self, char):
        """Handles all button clicks"""
        
        if char == "AC":
            # Clear everything
            self.current_input = ""
            self.update_display("0")
            
        elif char == "=":
            # Calculate the result
            try:
                # eval() is a simple way to calculate a string like "2 + 2"
                # Be careful using eval in large security-sensitive apps
                result = str(eval(self.current_input))
                self.update_display(result)
                self.current_input = result
            except:
                self.update_display("Error")
                self.current_input = ""
                
        else:
            # Add the number or operator to the string
            self.current_input += char
            self.update_display(self.current_input)

    def update_display(self, text):
        self.serial_text.config(text=text)

# Run the app
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("300x400") # Set a default size
    
    # 4. FIX: actually instantiate the class!
    app = SimplePaintApp(root)
    
    root.mainloop()