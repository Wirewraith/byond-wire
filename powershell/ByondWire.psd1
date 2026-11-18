@{
    RootModule = 'ByondWire.psm1'
    ModuleVersion = '0.1.2'
    GUID = 'b6325740-a5c1-4b98-b817-9dbfa3377f93'
    Author = 'Wirewraith'
    Copyright = '(c) 2026 Wirewraith. MIT license.'
    Description = 'Small standard-library BYOND Topic client.'
    PowerShellVersion = '7.4'
    CompatiblePSEditions = @('Core')
    FunctionsToExport = @('Invoke-ByondTopic', 'ConvertFrom-ByondText')
    CmdletsToExport = @()
    VariablesToExport = @()
    AliasesToExport = @()
    PrivateData = @{
        PSData = @{
            Tags = @('BYOND', 'Topic', 'Networking')
            LicenseUri = 'https://github.com/Wirewraith/byond-wire/blob/main/LICENSE'
            ProjectUri = 'https://github.com/Wirewraith/byond-wire'
        }
    }
}
