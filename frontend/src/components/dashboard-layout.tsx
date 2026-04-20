import { Button } from '@/components/ui/button';
import {
  MoonIcon,
  SunIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MenuIcon,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { cn } from '@/utils';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { useAuth } from '@/hooks/useAuth';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Link } from 'react-router-dom';
import logo from '@/assets/COMPASS-logo.svg';
import logoIcon from '@/assets/compass-icon.png';

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const { user, logout } = useAuth();

  // Derive display name: Auth0 name (if real name, not email) > first part of email, capitalized
  const rawName = user?.name && !user.name.includes('@') ? user.name : null;
  const displayName = rawName
    || (user?.email ? user.email.split('@')[0].replace(/[._-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'User');

  useEffect(() => {
    const check = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      setSidebarCollapsed(mobile);
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
  };

  return (
    <div className={cn('min-h-screen bg-gray-50 dark:bg-gray-900', theme)}>
      <div className="flex h-screen overflow-hidden">
        {/* Sidebar — hidden on mobile */}
        {!isMobile && (
          <aside
            className={cn(
              'flex flex-col h-full bg-background border-r transition-all duration-300 ease-in-out z-30',
              sidebarCollapsed ? 'w-16' : 'w-64'
            )}
          >
            <div className="flex items-center justify-center p-6 border-b">
              <img
                src={logo}
                alt="Commodities Compass Logo"
                className={cn(
                  'object-contain transition-all duration-300',
                  sidebarCollapsed ? 'h-12 w-12' : 'h-40 w-40'
                )}
              />
            </div>

            <div className="flex-1 overflow-y-auto py-4">
              <nav className="px-2 space-y-1">
                <Button
                  variant="ghost"
                  className={cn(
                    'w-full justify-start',
                    sidebarCollapsed ? 'px-2' : 'px-3'
                  )}
                  asChild
                >
                  <Link to="/dashboard">
                    <LayoutDashboardIcon
                      className={cn(
                        'h-5 w-5',
                        sidebarCollapsed ? 'mr-0' : 'mr-3'
                      )}
                    />
                    {!sidebarCollapsed && <span>Cacao</span>}
                  </Link>
                </Button>
              </nav>
            </div>

            <div className="border-t p-4">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className={cn(
                      'w-full flex items-center',
                      sidebarCollapsed ? 'justify-center' : 'justify-start'
                    )}
                  >
                    <Avatar className="h-8 w-8">
                      <AvatarImage
                        src={user?.picture}
                        alt={user?.name || 'User'}
                      />
                      <AvatarFallback>
                        {displayName.split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join('')}
                      </AvatarFallback>
                    </Avatar>
                    {!sidebarCollapsed && (
                      <div className="ml-3 text-left truncate">
                        <p className="text-sm font-medium truncate">{displayName}</p>
                        {user?.email && <p className="text-xs text-muted-foreground truncate">{user.email}</p>}
                      </div>
                    )}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="right">
                  <DropdownMenuLabel>Mon Compte</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={toggleTheme}>
                    {theme === 'light' ? (
                      <MoonIcon className="mr-2 h-4 w-4" />
                    ) : (
                      <SunIcon className="mr-2 h-4 w-4" />
                    )}
                    {theme === 'light' ? 'Mode Sombre' : 'Mode Clair'}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout}>
                    <LogOutIcon className="mr-2 h-4 w-4" />
                    Déconnexion
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </aside>
        )}

        {/* Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Mobile top bar */}
          {isMobile && (
            <header className="flex items-center justify-between px-4 py-3 border-b bg-background">
              <img src={logoIcon} alt="Compass" className="h-8 w-8 object-contain" />

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-9 w-9">
                    <MenuIcon className="h-5 w-5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel className="flex items-center gap-2">
                    <Avatar className="h-6 w-6">
                      <AvatarImage src={user?.picture} alt={user?.name || 'User'} />
                      <AvatarFallback className="text-[10px]">
                        {displayName.split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join('')}
                      </AvatarFallback>
                    </Avatar>
                    <div className="truncate">
                      <p className="text-sm font-medium truncate">{displayName}</p>
                      {user?.email && <p className="text-xs text-muted-foreground font-normal truncate">{user.email}</p>}
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={toggleTheme}>
                    {theme === 'light' ? (
                      <MoonIcon className="mr-2 h-4 w-4" />
                    ) : (
                      <SunIcon className="mr-2 h-4 w-4" />
                    )}
                    {theme === 'light' ? 'Mode Sombre' : 'Mode Clair'}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout}>
                    <LogOutIcon className="mr-2 h-4 w-4" />
                    Déconnexion
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </header>
          )}

          <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
        </div>
      </div>
    </div>
  );
}
