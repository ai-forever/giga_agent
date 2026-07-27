import React, { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/components/providers/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle, Loader2 } from "lucide-react";
import LogoWhiteImage from "@/assets/gigachain_logo.svg";
import { API_AGENT_PREFIX } from "@/config.ts";

type JoinInfo = {
  valid: boolean;
  email: string | null;
  role: string | null;
};

/**
 * Публичная страница вступления в команду по ссылке-приглашению /join/<token>.
 * Проверяет токен, собирает имя/почту/пароль, создаёт аккаунт и сразу логинит.
 */
const JoinPage: React.FC = () => {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { token } = useParams<{ token: string }>();

  const [info, setInfo] = useState<JoinInfo | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(true);

  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(
          `${API_AGENT_PREFIX}/auth/join/${encodeURIComponent(token ?? "")}`,
        );
        const data = resp.ok ? await resp.json() : { valid: false };
        if (!cancelled) {
          setInfo(data);
          if (data?.email) setEmail(data.email);
        }
      } catch {
        if (!cancelled) setInfo({ valid: false, email: null, role: null });
      } finally {
        if (!cancelled) setLoadingInfo(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== password2) {
      setError("Пароли не совпадают");
      return;
    }
    setIsSubmitting(true);
    try {
      const resp = await fetch(`${API_AGENT_PREFIX}/auth/join`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          email,
          password,
          first_name: firstName || null,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(
          err.message || err.detail || "Не удалось принять приглашение",
        );
      }
      // Аккаунт создан — входим обычным логином (заполняет auth-контекст).
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка вступления");
    } finally {
      setIsSubmitting(false);
    }
  };

  const emailLocked = Boolean(info?.email);

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">
            Подключение к{" "}
            <img
              className="w-10 h-10 inline-block"
              src={LogoWhiteImage}
              alt="GigaAgent Logo"
            />{" "}
            GigaAgent
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loadingInfo ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : !info?.valid ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Приглашение недействительно или истекло. Запросите новую ссылку
                у администратора.
              </AlertDescription>
            </Alert>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <p className="text-sm text-muted-foreground text-center">
                Вас пригласили в команду
                {info.role === "admin" ? " администратором" : ""}. Создайте
                аккаунт, чтобы продолжить.
              </p>

              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="join-name">Имя</Label>
                <Input
                  id="join-name"
                  placeholder="Как к вам обращаться"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  autoComplete="given-name"
                  disabled={isSubmitting}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="join-email">Email</Label>
                <Input
                  id="join-email"
                  type="email"
                  placeholder="user@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  disabled={isSubmitting || emailLocked}
                />
                {emailLocked && (
                  <p className="text-xs text-muted-foreground">
                    Приглашение выписано на эту почту
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="join-password">Пароль</Label>
                <PasswordInput
                  id="join-password"
                  placeholder="Минимум 8 символов"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  disabled={isSubmitting}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="join-password2">Пароль ещё раз</Label>
                <PasswordInput
                  id="join-password2"
                  placeholder="••••••••"
                  value={password2}
                  onChange={(e) => setPassword2(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  disabled={isSubmitting}
                />
              </div>

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Создаём аккаунт…
                  </>
                ) : (
                  "Присоединиться"
                )}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default JoinPage;
