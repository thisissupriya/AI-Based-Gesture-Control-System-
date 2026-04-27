import json
import os
import sys

# Add current dir to path to import ActionMap
sys.path.append(os.getcwd())

from action_map import ActionMap

def test_multi_mapping():
    config_file = "test_action_config.json"
    if os.path.exists(config_file):
        os.remove(config_file)
        
    am = ActionMap(config_file=config_file)
    
    # Map multiple gestures
    am.map_gesture("fist", "volume_mute")
    am.map_gesture("palm", "media_play_pause")
    am.map_gesture("ok", "browser_refresh")
    
    # Reload and verify
    am2 = ActionMap(config_file=config_file)
    print(f"Global Mappings: {am2.mapping}")
    
    assert am2.mapping.get("fist") == "volume_mute"
    assert am2.mapping.get("palm") == "media_play_pause"
    assert am2.mapping.get("ok") == "browser_refresh"
    
    # Test app-specific
    am2.map_gesture("palm", "ppt_next", app_name="powerpnt.exe")
    
    # Reload and verify
    am3 = ActionMap(config_file=config_file)
    apps = am3.mapping_data.get("profiles", {}).get("default", {}).get("apps", {})
    print(f"App Mappings: {apps}")
    
    assert apps.get("powerpnt.exe", {}).get("palm") == "ppt_next"
    assert am3.mapping.get("palm") == "media_play_pause" # Global still exists
    
    print("Test passed!")
    
    if os.path.exists(config_file):
        os.remove(config_file)

if __name__ == "__main__":
    test_multi_mapping()
