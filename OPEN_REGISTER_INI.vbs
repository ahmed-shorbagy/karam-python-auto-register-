' Opens register.ini in Notepad (works if .bat does nothing on double-click)
Option Explicit
Dim fso, sh, folder, ini, tpl
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
ini = folder & "\register.ini"
tpl = folder & "\register.ini.template"

If Not fso.FileExists(ini) Then
    If fso.FileExists(tpl) Then
        fso.CopyFile tpl, ini, True
    Else
        MsgBox "لم يُعثر على register.ini" & vbCrLf & vbCrLf & _
            "فك ضغط الـ ZIP كاملاً إلى مجلد ثم أعد المحاولة.", vbCritical, "Karama"
        WScript.Quit 1
    End If
End If

MsgBox "سيفتح Notepad." & vbCrLf & vbCrLf & _
    "عدّل TELEGRAM_BOT و TELEGRAM_CHANNEL ثم احفظ (Ctrl+S).", vbInformation, "إعدادات تيليجرام"

sh.Run "notepad.exe """ & ini & """", 1, True

MsgBox "إذا حفظت الملف، شغّل: 2 - اختبار تيليجرام.bat", vbInformation, "تم"
