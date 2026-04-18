#!/bin/bash
# Setup Appium + Android tools sur Mac Apple Silicon
set -e

echo "Installation Java 17..."
brew install openjdk@17
sudo ln -sfn /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk /Library/Java/JavaVirtualMachines/openjdk-17.jdk 2>/dev/null || true
echo 'export JAVA_HOME=/opt/homebrew/opt/openjdk@17' >> ~/.zprofile
echo 'export PATH="$JAVA_HOME/bin:$PATH"' >> ~/.zprofile
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PATH="$JAVA_HOME/bin:$PATH"

echo "Installation Appium..."
npm install -g appium@latest
appium driver install uiautomator2

echo "Installation Python client Appium..."
pip3 install Appium-Python-Client selenium

echo "Verification..."
java -version
node -v
appium --version

echo ""
echo "Prochaine etape :"
echo "  1. Ouvre Android Studio"
echo "  2. Virtual Device Manager -> demarre un emulateur"
echo "  3. Lance : appium"
echo "  4. Lance : python3 grab_gen/calibrate.py"
