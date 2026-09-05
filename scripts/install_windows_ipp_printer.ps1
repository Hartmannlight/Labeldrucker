#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$PrinterName = "PrintHub 50x25 Label",
    [string]$IppUrl = "http://localhost:8631/ipp/print",
    [ValidateRange(0.1, 10000.0)]
    [double]$WidthMm = 50.0,
    [ValidateRange(0.1, 10000.0)]
    [double]$HeightMm = 25.0,
    [switch]$Recreate,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-Millimeters {
    param([double]$PrintSchemaUnits)
    return $PrintSchemaUnits / 96.0 * 25.4
}

function Test-MediaSize {
    param(
        [System.Printing.PageMediaSize]$MediaSize,
        [double]$ExpectedWidthMm,
        [double]$ExpectedHeightMm
    )

    if (
        $null -eq $MediaSize -or
        $null -eq $MediaSize.Width -or
        $null -eq $MediaSize.Height
    ) {
        return $false
    }
    $actualWidthMm = ConvertTo-Millimeters $MediaSize.Width
    $actualHeightMm = ConvertTo-Millimeters $MediaSize.Height
    return (
        [Math]::Abs($actualWidthMm - $ExpectedWidthMm) -le 0.01 -and
        [Math]::Abs($actualHeightMm - $ExpectedHeightMm) -le 0.01
    )
}

function Test-AdvertisedMediaSize {
    param(
        [string]$CapabilitiesXml,
        [double]$ExpectedWidthMm,
        [double]$ExpectedHeightMm
    )

    $document = [xml]$CapabilitiesXml
    $options = $document.SelectNodes(
        "//*[local-name()='Feature' and @name='psk:PageMediaSize']/*[local-name()='Option']"
    )
    foreach ($option in $options) {
        $width = $option.SelectSingleNode(
            ".//*[local-name()='ScoredProperty' and @name='psk:MediaSizeWidth']/*[local-name()='Value']"
        )
        $height = $option.SelectSingleNode(
            ".//*[local-name()='ScoredProperty' and @name='psk:MediaSizeHeight']/*[local-name()='Value']"
        )
        if ($null -eq $width -or $null -eq $height) {
            continue
        }
        if (
            [Math]::Abs(([double]$width.InnerText / 1000.0) - $ExpectedWidthMm) -le 0.01 -and
            [Math]::Abs(([double]$height.InnerText / 1000.0) - $ExpectedHeightMm) -le 0.01
        ) {
            return $true
        }
    }
    return $false
}

if ($CheckOnly -and $Recreate) {
    throw "-CheckOnly and -Recreate cannot be used together."
}

$existingPrinter = Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue
if ($CheckOnly -and $null -eq $existingPrinter) {
    throw "Printer '$PrinterName' is not installed."
}

if (-not $CheckOnly) {
    if ($Recreate -and $null -ne $existingPrinter) {
        if (-not (Test-IsAdministrator)) {
            throw "Run -Recreate from a PowerShell started as Administrator."
        }
        Remove-Printer -Name $PrinterName
        $existingPrinter = $null
    }
    if ($null -eq $existingPrinter) {
        if (-not (Test-IsAdministrator)) {
            throw "Install the queue from a PowerShell started as Administrator."
        }
        Add-Printer -Name $PrinterName -IppURL $IppUrl
    }
}

Add-Type -AssemblyName System.Printing
$printServer = [System.Printing.LocalPrintServer]::new()
$queue = $printServer.GetPrintQueue($PrinterName)
$queue.Refresh()

$configuration = Get-PrintConfiguration -PrinterName $PrinterName
if (-not (Test-AdvertisedMediaSize $configuration.PrintCapabilitiesXML $WidthMm $HeightMm)) {
    throw "Printer '$PrinterName' does not advertise ${WidthMm} x ${HeightMm} mm."
}

if (-not $CheckOnly) {
    $widthUnits = $WidthMm / 25.4 * 96.0
    $heightUnits = $HeightMm / 25.4 * 96.0
    $mediaDelta = [System.Printing.PrintTicket]::new()
    $mediaDelta.PageMediaSize = [System.Printing.PageMediaSize]::new(
        $widthUnits,
        $heightUnits
    )

    $userResult = $queue.MergeAndValidatePrintTicket(
        $queue.UserPrintTicket,
        $mediaDelta
    )
    if ($userResult.ConflictStatus -ne [System.Printing.ConflictStatus]::NoConflict) {
        throw "Windows rejected ${WidthMm} x ${HeightMm} mm for '$PrinterName'."
    }

    $queue.UserPrintTicket = $userResult.ValidatedPrintTicket
    $queue.Commit()
    $queue.Refresh()
}

$defaultMedia = $queue.DefaultPrintTicket.PageMediaSize
$userMedia = $queue.UserPrintTicket.PageMediaSize
$defaultValid = Test-MediaSize $defaultMedia $WidthMm $HeightMm
$userValid = Test-MediaSize $userMedia $WidthMm $HeightMm
if (-not $userValid) {
    throw (
        "Printer '$PrinterName' has an invalid user media ticket: " +
        "$([Math]::Round((ConvertTo-Millimeters $userMedia.Width), 3)) x " +
        "$([Math]::Round((ConvertTo-Millimeters $userMedia.Height), 3)) mm."
    )
}

[pscustomobject]@{
    PrinterName = $PrinterName
    Driver = $queue.QueueDriver.Name
    QueueStatus = $queue.QueueStatus
    Jobs = $queue.NumberOfJobs
    WidthMm = [Math]::Round((ConvertTo-Millimeters $userMedia.Width), 3)
    HeightMm = [Math]::Round((ConvertTo-Millimeters $userMedia.Height), 3)
    UserTicketValid = $userValid
    DriverDefaultWidthMm = [Math]::Round((ConvertTo-Millimeters $defaultMedia.Width), 3)
    DriverDefaultHeightMm = [Math]::Round((ConvertTo-Millimeters $defaultMedia.Height), 3)
    DriverDefaultMatches = $defaultValid
}
