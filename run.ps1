param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$SearchArguments = @("--help")
)

docker build -t digital-detective .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker run --rm -v "${PWD}/reports:/reports" digital-detective @SearchArguments --output-dir /reports
