"""
Calibration — explore l'interface Grab app pour trouver les bons selecteurs
Usage : python3 grab_gen/calibrate.py [device_id]
"""
import sys, json
from pathlib import Path

def main():
    device_id = sys.argv[1] if len(sys.argv) > 1 else "emulator-5554"
    print(f"[Calibrate] Device : {device_id}")
    print("[Calibrate] Connexion Appium...")

    from grab_gen.grab_app import GrabApp

    with GrabApp(device_id) as app:
        print("[Calibrate] Connecte — exploration...")
        info = app.explore()
        print(f"\n=== ECRAN INITIAL — Elements cliquables ({len(info['clickable'])}) ===")
        for e in info["clickable"]:
            text = e.get("text","")[:50]
            rid  = e.get("id","")
            desc = e.get("desc","")[:40]
            cls  = (e.get("class","") or "").split(".")[-1]
            print(f"  [{cls:20}] text='{text:40}' id='{rid}' desc='{desc}'")

        # Screenshot
        app.screenshot("/tmp/grab_calibrate.png")
        print("\nScreenshot -> /tmp/grab_calibrate.png")

        # Try to navigate to signup
        print("\n[Calibrate] Test navigation signup...")
        ok = app.navigate_to_signup()
        print(f"  -> {'OK' if ok else 'Echec'}")

        if ok:
            app.screenshot("/tmp/grab_calibrate_signup.png")
            print("Screenshot signup -> /tmp/grab_calibrate_signup.png")
            info2 = app.explore()
            print(f"\nElements apres navigation ({len(info2['clickable'])}) :")
            for e in info2["clickable"]:
                text = e.get("text","")[:40]
                rid  = e.get("id","")
                if text or rid:
                    print(f"  text='{text}' id='{rid}'")

        print("\nCalibration terminee")
        print("   Envoie les logs pour ajuster les selecteurs dans grab_app.py")

if __name__ == "__main__":
    main()
