def get_system_text(custom_instructions=None):
    system_message = ""  # Initialize system message

    # Add important marker if custom instructions are provided
    if custom_instructions:
        system_message += f"IMPORTANT: {custom_instructions}\n"

    # Additional system message logic
    # ...

    return system_message
