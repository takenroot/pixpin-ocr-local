' 静默启动 dePixPin 服务（无控制台窗口，供任务计划程序调用）
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
ws.Run "pythonw.exe -X utf8 """ & ws.CurrentDirectory & "\app.py"" --https", 0, False
