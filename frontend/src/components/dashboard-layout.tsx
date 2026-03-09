import { Button } from '@/components/ui/button';
import {
  MoonIcon,
  SunIcon,
  LayoutDashboardIcon,
  LogOutIcon,
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
  const { user, logout } = useAuth();

  // Check if mobile on mount and when window resizes
  useEffect(() => {
    const checkIfMobile = () => {
      if (window.innerWidth < 768) {
        setSidebarCollapsed(true);
      }
    };

    checkIfMobile();
    window.addEventListener('resize', checkIfMobile);

    return () => {
      window.removeEventListener('resize', checkIfMobile);
    };
  }, []);

  // Apply theme class on mount and changes
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
        {/* Sidebar */}
        <aside
          className={cn(
            'flex flex-col h-full bg-background border-r transition-all duration-300 ease-in-out z-30',
            sidebarCollapsed ? 'w-16' : 'w-64'
          )}
        >
          {/* Logo and App Name */}
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

          {/* Navigation */}
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

                  {!sidebarCollapsed && <span>Dashboard</span>}
                </Link>
              </Button>
              {/* <Button
                variant="ghost"
                className={cn(
                  'w-full justify-start',
                  sidebarCollapsed ? 'px-2' : 'px-3'
                )}
                asChild
              >
                <Link to="/dashboard/historical">
                  <HistoryIcon
                    className={cn(
                      'h-5 w-5',
                      sidebarCollapsed ? 'mr-0' : 'mr-3'
                    )}
                  />

                  {!sidebarCollapsed && <span>Historical Data</span>}
                </Link>
              </Button> */}
            </nav>
          </div>

          {/* User profile at bottom */}
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
                      {user?.name?.charAt(0)?.toUpperCase() || 'U'}
                    </AvatarFallback>
                  </Avatar>
                  {!sidebarCollapsed && (
                    <span className="ml-3 truncate">
                      {user?.name || user?.email || 'User Profile'}
                    </span>
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" side="right">
                <DropdownMenuLabel>My Account</DropdownMenuLabel>
                <DropdownMenuSeparator />

                <DropdownMenuItem onClick={toggleTheme}>
                  {theme === 'light' ? (
                    <MoonIcon className="mr-2 h-4 w-4" />
                  ) : (
                    <SunIcon className="mr-2 h-4 w-4" />
                  )}
                  {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />

                <DropdownMenuItem onClick={logout}>
                  <LogOutIcon className="mr-2 h-4 w-4" />
                  Log out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
