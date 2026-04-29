using System.IdentityModel.Tokens.Jwt;
using System.Text.Json;

namespace AuthenticationDemos.Web.Services;

public static class TokenHelper
{
    public static void LogTokenClaims(IDemoLogger logger, string token, string label)
    {
        try
        {
            var handler = new JwtSecurityTokenHandler();
            if (!handler.CanReadToken(token))
            {
                logger.Log(LogLevel.Warning, $"{label}: Token is not a readable JWT");
                return;
            }

            var jwt = handler.ReadJwtToken(token);

            logger.Log(LogLevel.Token, $"{label} — Token acquired successfully");
            logger.Log(LogLevel.Token, $"  Issuer: {jwt.Issuer}");
            logger.Log(LogLevel.Token, $"  Audience: {string.Join(", ", jwt.Audiences)}");
            logger.Log(LogLevel.Token, $"  Expires: {jwt.ValidTo:u}");
            logger.Log(LogLevel.Token, $"  Not Before: {jwt.ValidFrom:u}");

            foreach (var claim in jwt.Claims)
            {
                logger.Log(LogLevel.Claim, $"  {claim.Type}: {claim.Value}");
            }
        }
        catch (Exception ex)
        {
            logger.Log(LogLevel.Warning, $"{label}: Could not decode token — {ex.Message}");
        }
    }
}
