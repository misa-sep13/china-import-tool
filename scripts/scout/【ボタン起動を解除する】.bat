@echo off
chcp 65001 > nul
echo ============================================================
echo  セラースカウト  ボタン起動の解除
echo ============================================================
echo.
echo  「更新する」ボタンからこのPCで巡回を始める登録を消します。
echo  巡回そのものは【巡回する】.bat で今までどおり実行できます。
echo.
pause
reg delete "HKCU\Software\Classes\scout" /f > nul 2>&1
echo.
echo  解除しました。
echo.
pause
