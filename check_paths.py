import sys, os, json

# Add FreeCAD lib path
sys.path.insert(0, '/opt/freecad/squashfs-root/lib')

try:
    import FreeCAD
    print("=== FreeCAD loaded OK ===")
    print("UserAppData:", FreeCAD.getUserAppData())
    
    # Check what paths FreeCAD uses for Mod
    user_mod = os.path.join(FreeCAD.getUserAppData(), "Mod")
    print("User Mod path:", user_mod)
    print("User Mod exists:", os.path.exists(user_mod))
    if os.path.exists(user_mod):
        print("User Mod contents:", os.listdir(user_mod))
    
    # Also check standard paths
    for base in ["/config/.FreeCAD", "/config/.config/FreeCAD"]:
        if os.path.exists(base):
            print(f"\n=== {base} ===")
            for root, dirs, files in os.walk(base):
                level = root.replace(base, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f'{indent}{os.path.basename(root)}/')
                if level < 3:
                    subindent = ' ' * 2 * (level + 1)
                    for f in files[:5]:
                        print(f'{subindent}{f}')
                    if len(files) > 5:
                        print(f'{subindent}... +{len(files)-5} more')

    # Check Mod directories specifically
    for path in ["/config/.FreeCAD/Mod", "/config/.config/FreeCAD/Mod"]:
        if os.path.exists(path):
            print(f"\n=== {path} ===")
            print("Contents:", os.listdir(path))
        else:
            print(f"\n=== {path} DOES NOT EXIST ===")

except Exception as e:
    import traceback
    print("Error:", e)
    traceback.print_exc()
